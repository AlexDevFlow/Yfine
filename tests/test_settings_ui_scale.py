"""Tests for the ui_scale setting (Compact / Normal / Large / Extra Large)."""
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


class TestUiScaleSetting:
    def test_default_is_normal(self, session):
        s = _make_setting(session)
        assert s.ui_scale == "normal"

    def test_get_settings_creates_default(self, session):
        s = settings_service.get_settings(session)
        assert s.ui_scale == "normal"

    @pytest.mark.parametrize("value", ["small", "normal", "large", "xlarge"])
    def test_update_persists_valid_values(self, session, value):
        _make_setting(session)
        updated = settings_service.update_settings(session, SettingUpdate(ui_scale=value))
        assert updated.ui_scale == value
        # Reading back from a fresh fetch goes through the DB
        assert settings_service.get_settings(session).ui_scale == value

    def test_update_propagates_to_i18n_module(self, session):
        from i18n import get_ui_scale
        _make_setting(session)
        settings_service.update_settings(session, SettingUpdate(ui_scale="large"))
        assert get_ui_scale() == "large"
        settings_service.update_settings(session, SettingUpdate(ui_scale="small"))
        assert get_ui_scale() == "small"

    def test_invalid_value_ignored_by_i18n_setter(self):
        """The i18n setter is the last line of defense — unknown values must
        not corrupt the in-memory state."""
        from i18n import set_ui_scale, get_ui_scale
        set_ui_scale("normal")
        set_ui_scale("gigantic")  # unknown
        assert get_ui_scale() == "normal"
        set_ui_scale("")  # empty
        assert get_ui_scale() == "normal"

    def test_update_does_not_touch_other_fields(self, session):
        _make_setting(session)
        before = settings_service.update_settings(
            session, SettingUpdate(theme="dark", locale="it")
        )
        # ui_scale stays at default
        assert before.ui_scale == "normal"
        # Now update only ui_scale
        after = settings_service.update_settings(session, SettingUpdate(ui_scale="xlarge"))
        assert after.ui_scale == "xlarge"
        assert after.theme == "dark"
        assert after.locale == "it"


class TestUiScaleTemplate:
    """Pin the integration into the base template + settings page so a future
    refactor does not silently drop the control."""

    def test_base_template_emits_data_ui_scale(self):
        with open("templates/base.html") as f:
            html = f.read()
        assert "data-ui-scale" in html
        assert "get_ui_scale()" in html

    def test_settings_page_has_ui_scale_buttons(self):
        with open("templates/settings/index.html") as f:
            html = f.read()
        assert 'class="ui-scale-btn' in html or "ui-scale-btn" in html
        for scale in ("small", "normal", "large", "xlarge"):
            assert f'data-scale="{scale}"' in html
        assert 'id="ui_scale"' in html

    def test_css_rules_present(self):
        with open("static/css/yfine.css") as f:
            css = f.read()
        for scale in ("small", "normal", "large", "xlarge"):
            assert f'data-ui-scale="{scale}"' in css


class TestUiScaleLocales:
    """ui_size and the four labels must exist in every locale."""

    def test_keys_in_all_locales(self):
        import json
        keys = ["ui_size", "ui_size_small", "ui_size_normal",
                "ui_size_large", "ui_size_xlarge", "ui_size_desc"]
        for f in ["locales/en.json", "locales/it.json",
                  "locales/es.json", "locales/uk.json"]:
            with open(f) as fh:
                data = json.load(fh)
            for k in keys:
                assert k in data, f"{k} missing in {f}"
