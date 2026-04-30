"""Tests for keyboard-shortcut settings + sidebar layout customization."""
import json

import pytest

from models.setting import Setting
from schemas.setting import SettingUpdate
from services import settings as settings_service


def _make_setting(session):
    s = Setting(id=1)
    session.add(s)
    session.commit()
    session.refresh(s)
    return s


# ── Hotkeys ──────────────────────────────────────────────────────


class TestHotkeysSetting:
    def test_defaults(self, session):
        s = _make_setting(session)
        assert s.hotkeys_enabled is True
        assert s.hotkeys_json == "{}"

    def test_master_toggle_persists(self, session):
        _make_setting(session)
        updated = settings_service.update_settings(
            session, SettingUpdate(hotkeys_enabled=False)
        )
        assert updated.hotkeys_enabled is False
        # Re-read from DB
        assert settings_service.get_settings(session).hotkeys_enabled is False

    def test_master_toggle_propagates_to_i18n(self, session):
        from i18n import get_hotkeys_enabled
        _make_setting(session)
        settings_service.update_settings(session, SettingUpdate(hotkeys_enabled=False))
        assert get_hotkeys_enabled() is False
        settings_service.update_settings(session, SettingUpdate(hotkeys_enabled=True))
        assert get_hotkeys_enabled() is True

    def test_user_overrides_persist_and_propagate(self, session):
        from i18n import get_hotkeys_json
        _make_setting(session)
        overrides = {"nav_dashboard": "h", "focus_search": ""}
        settings_service.update_settings(
            session, SettingUpdate(hotkeys_json=json.dumps(overrides))
        )
        # i18n module mirror is updated synchronously
        assert json.loads(get_hotkeys_json()) == overrides
        # And the DB row matches
        assert json.loads(settings_service.get_settings(session).hotkeys_json) == overrides

    def test_only_overrides_stored_not_full_default_set(self, session):
        """Convention check: the JSON column stores user overrides only.
        The defaults live in static/js/hotkeys.js (single source of truth);
        future default tweaks must reach existing users without a migration.
        Test guards that against a future regression where someone makes
        update_settings backfill defaults into the column."""
        _make_setting(session)
        settings_service.update_settings(session, SettingUpdate(hotkeys_json="{}"))
        assert settings_service.get_settings(session).hotkeys_json == "{}"


# ── Sidebar layout ──────────────────────────────────────────────


class TestNavLayout:
    def test_default_returns_all_items_visible(self, session):
        from i18n import get_nav_items, set_nav_layout_json, DEFAULT_NAV_ITEMS
        set_nav_layout_json("[]")
        items = get_nav_items()
        assert len(items) == len(DEFAULT_NAV_ITEMS)
        assert all(i["visible"] for i in items)
        # Default order matches DEFAULT_NAV_ITEMS
        assert [i["id"] for i in items] == [d["id"] for d in DEFAULT_NAV_ITEMS]

    def test_custom_order_respected(self, session):
        from i18n import get_nav_items, set_nav_layout_json
        # Reverse a couple of items
        layout = [
            {"id": "settings",    "visible": True},
            {"id": "dashboard",   "visible": True},
        ]
        set_nav_layout_json(json.dumps(layout))
        items = get_nav_items()
        first_two = [i["id"] for i in items[:2]]
        assert first_two == ["settings", "dashboard"]

    def test_hidden_items_kept_in_list_but_marked(self, session):
        """Hidden items are still returned by get_nav_items so the settings
        page can render the toggle in the OFF position. base.html filters
        them out at render time via `selectattr('visible')`."""
        from i18n import get_nav_items, set_nav_layout_json
        layout = [{"id": "tags", "visible": False}]
        set_nav_layout_json(json.dumps(layout))
        items = get_nav_items()
        tags = next((i for i in items if i["id"] == "tags"), None)
        assert tags is not None
        assert tags["visible"] is False

    def test_unknown_ids_in_saved_layout_dropped(self, session):
        """If a future build removes a nav id (or the user pasted garbage)
        the unknown id must be silently ignored, not raise."""
        from i18n import get_nav_items, set_nav_layout_json
        set_nav_layout_json(json.dumps([
            {"id": "ghost",     "visible": True},
            {"id": "dashboard", "visible": True},
        ]))
        items = get_nav_items()
        assert "ghost" not in [i["id"] for i in items]
        assert items[0]["id"] == "dashboard"

    def test_missing_items_appended_default_visible(self, session):
        """Forward compatibility: a saved layout from an older build that
        doesn't mention a newly-added nav entry must still surface it
        (visible by default), not silently hide it."""
        from i18n import get_nav_items, set_nav_layout_json
        # Saved layout only mentions one item — every other default must be
        # appended afterwards with visible=True.
        set_nav_layout_json(json.dumps([{"id": "movements", "visible": False}]))
        items = get_nav_items()
        ids = [i["id"] for i in items]
        # All defaults present
        assert {"dashboard", "sources", "portfolios", "movements", "tags",
                "recurring", "savings", "whims", "notifications", "settings"} <= set(ids)
        # The mentioned one is hidden; every appended one is visible
        for it in items:
            if it["id"] == "movements":
                assert it["visible"] is False
            else:
                assert it["visible"] is True

    def test_invalid_json_falls_back_to_defaults(self, session):
        from i18n import get_nav_items, set_nav_layout_json
        set_nav_layout_json("this is not json")
        items = get_nav_items()
        assert len(items) > 0  # didn't blow up, returned defaults
        assert all(i["visible"] for i in items)

    def test_duplicate_ids_in_layout_first_wins(self, session):
        from i18n import get_nav_items, set_nav_layout_json
        set_nav_layout_json(json.dumps([
            {"id": "dashboard", "visible": False},
            {"id": "dashboard", "visible": True},  # ignored
        ]))
        items = get_nav_items()
        dash = next(i for i in items if i["id"] == "dashboard")
        assert dash["visible"] is False


# ── Template integration ────────────────────────────────────────


class TestBaseTemplateWiring:
    """Pin the data-* contract that the front-end JS reads. If a refactor
    drops these attributes the runtime listener silently disengages."""

    def test_html_tag_carries_hotkey_attrs(self):
        with open("templates/base.html") as f:
            html = f.read()
        assert "data-hotkeys-enabled=" in html
        assert "data-hotkeys-json=" in html

    def test_helpers_loaded_before_page_js(self):
        """`hotkeys.js` and `math-input.js` must come BEFORE the page_js
        block. The Settings page reads `window.YN_HOTKEY_ACTIONS` (defined
        in hotkeys.js) inside its inline script to build the shortcuts
        table — if helpers loaded after page_js the table renders empty.
        Helpers only call into late-defined globals (toggleDarkMode etc.)
        lazily, when an action fires, so loading them earlier is safe."""
        with open("templates/base.html") as f:
            html = f.read()
        page_js_pos = html.find("{% block page_js %}{% endblock %}")
        hotkeys_pos = html.find("hotkeys.js")
        math_pos = html.find("math-input.js")
        assert page_js_pos != -1
        assert hotkeys_pos != -1 and math_pos != -1
        assert hotkeys_pos < page_js_pos
        assert math_pos < page_js_pos


class TestMoneyInputsMarked:
    """Every form that takes an amount must set `data-money` on the input,
    or the math helper won't pick it up. List grows over time — keep
    coverage explicit so a missed input doesn't slip past code review."""

    @pytest.mark.parametrize("path,marker", [
        ("templates/movements/form.html",   'id="amount"'),
        ("templates/recurring/form.html",   'id="amount"'),
        ("templates/savings/form.html",     'id="amount"'),
        ("templates/whims/form.html",       'id="amount"'),
        ("templates/sources/form.html",     'id="starting_balance"'),
        ("templates/portfolios/detail.html", 'id="h_quantity"'),
        ("templates/portfolios/detail.html", 'id="h_avg_cost"'),
        ("templates/portfolios/detail.html", 'id="h_last_price"'),
    ])
    def test_input_has_data_money(self, path, marker):
        with open(path) as f:
            html = f.read()
        # Look for the line containing the marker and assert data-money is on it
        for line in html.splitlines():
            if marker in line:
                assert "data-money" in line, f"{path}: input {marker} missing data-money"
                return
        pytest.fail(f"{path}: marker {marker} not found")


class TestSettingsPageNewTabs:
    def test_menu_layout_tab_present(self):
        with open("templates/settings/index.html") as f:
            html = f.read()
        assert 'id="tab-menu"' in html
        assert 'id="nav-layout-list"' in html
        # Drag-and-drop reordering: rows are draggable, drop indicators exist
        assert "nav-layout-item" in html
        assert 'draggable="true"' in html
        assert "nav-visible-cb" in html

    def test_menu_layout_uses_native_drag_not_arrow_buttons(self):
        """Drag-and-drop replaced the arrow buttons. Pin that change so
        nobody re-adds the arrows by accident — they would be redundant
        and clutter the row."""
        with open("templates/settings/index.html") as f:
            html = f.read()
        assert "nav-up-btn" not in html
        assert "nav-down-btn" not in html
        # JS handles the native dragstart/dragover/drop events
        assert "dragstart" in html and "dragover" in html and "drop" in html

    def test_menu_layout_change_auto_reloads(self):
        """After saving a new layout the settings page must `location.reload()`
        so the actual sidebar (rendered server-side) reflects the change.
        Optimistic in-page rewrites would mean keeping two renderers in sync."""
        with open("templates/settings/index.html") as f:
            html = f.read()
        # Inside the navLayout IIFE: reload after save
        nav_block_start = html.find("function navLayout()")
        nav_block_end = html.find("})();", nav_block_start)
        assert nav_block_start != -1 and nav_block_end != -1
        nav_block = html[nav_block_start:nav_block_end]
        assert "location.reload()" in nav_block

    def test_hotkeys_tab_present(self):
        with open("templates/settings/index.html") as f:
            html = f.read()
        assert 'id="tab-hotkeys"' in html
        assert 'id="hotkeys-table"' in html
        assert 'id="hotkeys_enabled"' in html


class TestNewLocaleKeys:
    """Every UI string introduced by hotkeys + menu layout must exist in
    every locale or rendering shows the raw key, which looks broken."""

    HOTKEY_KEYS = [
        "hotkeys", "hotkeys_master_toggle", "hotkeys_desc",
        "hotkeys_capture_hint", "hotkeys_press_keys",
        "action", "shortcut", "reset",
        "hotkey_nav_dashboard", "hotkey_nav_sources", "hotkey_nav_portfolios",
        "hotkey_nav_movements", "hotkey_nav_tags", "hotkey_nav_recurring",
        "hotkey_nav_savings", "hotkey_nav_whims", "hotkey_nav_notifications",
        "hotkey_nav_settings", "hotkey_new_movement", "hotkey_new_recurring",
        "hotkey_focus_search", "hotkey_toggle_theme",
    ]
    NAV_KEYS = [
        "menu_layout", "menu_layout_desc", "drag_to_reorder",
        "visible", "reset_to_default",
    ]

    @pytest.mark.parametrize("locale", ["en", "it", "es", "uk"])
    def test_all_keys_present(self, locale):
        with open(f"locales/{locale}.json") as f:
            data = json.load(f)
        for k in self.HOTKEY_KEYS + self.NAV_KEYS:
            assert k in data, f"{k} missing in locales/{locale}.json"
