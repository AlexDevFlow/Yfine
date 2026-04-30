"""Template regressions for the redesigned attachment UI (tile grid + lightbox).

Pure template/CSS regressions: pin the new structure so a future refactor
doesn't silently fall back to the old chip-based layout, and so the
lightbox markup the JS depends on stays in place.
"""


class TestUploadTileLayout:
    """Movement form: tile-based upload with thumbnails + remove overlay."""

    PATH = "templates/movements/form.html"

    def test_dropzone_polished(self):
        with open(self.PATH) as f:
            html = f.read()
        # New polished dropzone has icon + title + hint, with keyboard support
        assert 'class="yn-attach-drop"' in html
        assert 'tabindex="0"' in html
        assert "yn-attach-drop-icon" in html
        assert "yn-attach-drop-title" in html
        assert "yn-attach-drop-hint" in html

    def test_attach_list_uses_grid(self):
        """The list of pending/uploaded files renders into a CSS grid, not
        a flex-wrap chip row. Pinning the class keeps the layout consistent
        with the viewer modal."""
        with open(self.PATH) as f:
            html = f.read()
        assert 'id="attach-list" class="yn-attach-grid"' in html

    def test_old_chip_classes_gone(self):
        """The old `.yn-attach-chip*` classes were replaced by `.yn-attach-tile*`.
        Catch a partial rollback that keeps the new dropzone but reintroduces
        the old chip rendering."""
        with open(self.PATH) as f:
            html = f.read()
        assert "yn-attach-chip" not in html

    def test_image_preview_via_object_url(self):
        """Tiles for image files build their thumbnail from `URL.createObjectURL`
        on the local File so the user sees the picture instantly, before the
        upload completes. Pin the API call so a future "simplification" that
        drops it doesn't silently regress UX."""
        with open(self.PATH) as f:
            html = f.read()
        assert "URL.createObjectURL" in html
        assert "URL.revokeObjectURL" in html  # cleanup on remove


class TestViewerModalAndLightbox:
    """Movements list: view-only attachments modal + image lightbox."""

    PATH = "templates/movements/index.html"

    def test_modal_count_badge(self):
        with open(self.PATH) as f:
            html = f.read()
        assert 'id="attachments-modal-count"' in html

    def test_grid_classes_used(self):
        with open(self.PATH) as f:
            html = f.read()
        # JS-built tiles use the same classes as the form
        assert "yn-attach-grid" in html
        assert "yn-attach-tile" in html

    def test_lightbox_markup_present(self):
        with open(self.PATH) as f:
            html = f.read()
        # Markup the JS depends on
        for el_id in ("attach-lightbox", "attach-lightbox-img",
                      "attach-lightbox-close", "attach-lightbox-prev",
                      "attach-lightbox-next", "attach-lightbox-caption-text",
                      "attach-lightbox-counter"):
            assert f'id="{el_id}"' in html, f"missing #{el_id} in lightbox"

    def test_lightbox_keyboard_controls_wired(self):
        """ESC closes, arrows navigate. These keyboard handlers are what
        makes the image carousel feel native; without them users can only
        click the small overlay buttons."""
        with open(self.PATH) as f:
            html = f.read()
        assert "ArrowLeft" in html and "ArrowRight" in html
        assert "Escape" in html

    def test_pdf_uses_external_open_not_lightbox(self):
        """Lightbox is for images only. PDFs route through `yfOpenExternal`
        (so pywebview hands them to the OS PDF viewer where pinch-zoom and
        page navigation work natively) and fall back to a new tab. A future
        "open everything in lightbox" simplification would break PDF UX."""
        with open(self.PATH) as f:
            html = f.read()
        assert "_openLightbox" in html
        assert "yfOpenExternal" in html


class TestNativeFilePicker:
    """Pywebview integration: the dropzone click must route through
    `pywebview.api.pick_attachments` (which calls `create_file_dialog`) so
    the user gets the OS-native file dialog instead of Qt's bundled one.
    The `<input type="file">` path is kept as a fallback for browser mode.
    """

    def test_api_method_exists(self):
        """Importing desktop.py also sets PYWEBVIEW_GUI=qt as a side effect,
        but the Api class itself imports fine without a running window —
        we only need to confirm the method is present on the class."""
        from desktop import Api
        assert hasattr(Api, "pick_attachments")

    def test_api_uses_open_dialog(self):
        """Pin the call to `webview.OPEN_DIALOG` with `allow_multiple=True`.
        A regression that flipped to SAVE_DIALOG (mistaken copy-paste from
        save_export) would silently break uploads."""
        import inspect
        from desktop import Api
        src = inspect.getsource(Api.pick_attachments)
        assert "OPEN_DIALOG" in src
        assert "allow_multiple=True" in src
        # Returns a list of dicts shaped {name, size, mime, b64}
        for key in ("name", "size", "mime", "b64"):
            assert f'"{key}"' in src

    def test_linux_prefers_zenity_then_kdialog(self):
        """On Linux, both `<input type=file>` and `webview.create_file_dialog`
        render through Qt's `QFileDialog`, which on stacks without
        xdg-desktop-portal looks like Qt's own widget — exactly what the
        user is trying to escape. Zenity (GNOME / Pop!_OS / XFCE) and
        kdialog (KDE) are the standard CLI hooks into the system-native
        chooser; pin that we still try them first before falling back."""
        import inspect
        from desktop import Api
        src = inspect.getsource(Api._linux_native_picker)
        # zenity is tried first
        zen_idx = src.find("zenity")
        kde_idx = src.find("kdialog")
        assert zen_idx != -1 and kde_idx != -1
        assert zen_idx < kde_idx
        # Zenity gets the right flags for multi-select with newline-separated paths
        assert "--multiple" in src
        assert "--separator=" in src
        # The `pick_attachments` orchestrator gates the Linux branch on platform
        outer = inspect.getsource(Api.pick_attachments)
        assert 'sys.platform.startswith("linux")' in outer

    def test_form_warns_when_pywebview_present_but_method_missing(self):
        """If pywebview is loaded but `pick_attachments` isn't on
        `pywebview.api`, the user is almost certainly running a previous
        build of the desktop process. Surface a toast with that hint
        instead of falling back silently to the Qt `<input type=file>`
        dialog the user is trying to escape."""
        with open("templates/movements/form.html") as f:
            html = f.read()
        assert "_isPywebview" in html
        assert "attachments_restart_for_native_picker" in html

    def test_method_is_exposed_to_javascript(self):
        """Defining `Api.pick_attachments` is half the story — pywebview
        only forwards methods that are explicitly registered with
        `window.expose(api.<method>)` in desktop.py. A method that exists
        on the class but isn't exposed shows up nowhere on
        `window.pywebview.api`, and the browser-fallback path runs
        instead — exactly the bug the user hit before this regression."""
        with open("desktop.py") as f:
            src = f.read()
        assert "window.expose(api.pick_attachments)" in src

    def test_form_routes_click_through_pywebview_api(self):
        with open("templates/movements/form.html") as f:
            html = f.read()
        # Browser fallback must remain
        assert "input.click()" in html
        # Native path
        assert "pywebview.api.pick_attachments" in html
        assert "_hasNativePicker" in html
        # File rebuild from base64 → real File object → existing pipeline
        assert "atob(" in html
        assert "new File(" in html


class TestAttachmentCSSPresent:
    """The visual redesign lives entirely in static/css/yfine.css. Pin the
    presence of the rules the templates rely on."""

    def test_tile_and_lightbox_rules_in_css(self):
        with open("static/css/yfine.css") as f:
            css = f.read()
        for rule in (
            ".yn-attach-drop ", ".yn-attach-drop.is-dragover",
            ".yn-attach-grid ", ".yn-attach-tile ", ".yn-attach-tile-thumb",
            ".yn-attach-tile-remove", ".yn-attach-tile.is-uploading",
            ".yn-attach-lightbox ", ".yn-attach-lightbox.is-open",
            ".yn-attach-lightbox-img", ".yn-attach-lightbox-nav",
        ):
            assert rule in css, f"CSS rule missing: {rule.strip()}"

    def test_old_chip_rules_removed(self):
        """If the old chip rules linger they fight the new tile layout for
        spacing and the form looks half-redesigned."""
        with open("static/css/yfine.css") as f:
            css = f.read()
        assert ".yn-attach-chip " not in css
        assert ".yn-attach-chip-link" not in css
        assert ".yn-attach-chip-remove" not in css
