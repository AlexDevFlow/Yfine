/* Yfine — keyboard shortcuts.
 *
 * Runtime contract: <html> is annotated with `data-hotkeys-enabled` ("1" or
 * "0") and `data-hotkeys-json` (a JSON object of user overrides). Defaults
 * live in YN_HOTKEY_ACTIONS below; user overrides for a key replace the
 * default, and an empty string disables that action entirely.
 *
 * Bindings come in three shapes:
 *   - single key:        "n", "/", "?"
 *   - modifier + key:    "Alt+m", "Ctrl+Shift+k"
 *   - chord (sequence):  "g d", "g s"  (two presses within 1.2s)
 *
 * Listeners are skipped while typing in inputs / textareas / contenteditable
 * to avoid swallowing keystrokes.
 */
(function() {
  'use strict';

  function _go(url) { return function() { window.location.href = url; }; }
  function _toggleTheme() {
    if (typeof window.toggleDarkMode === 'function') window.toggleDarkMode();
  }
  function _focusSearch() {
    var el = document.getElementById('global-search');
    if (el) { el.focus(); el.select && el.select(); }
  }

  var YN_HOTKEY_ACTIONS = {
    nav_dashboard:     { def: 'g d',   run: _go('/') },
    nav_sources:       { def: 'g s',   run: _go('/sources') },
    nav_portfolios:    { def: 'g p',   run: _go('/portfolios') },
    nav_movements:     { def: 'g m',   run: _go('/movements') },
    nav_tags:          { def: 'g t',   run: _go('/tags') },
    nav_recurring:     { def: 'g r',   run: _go('/recurring') },
    nav_savings:       { def: 'g v',   run: _go('/savings') },
    nav_whims:         { def: 'g w',   run: _go('/whims') },
    nav_notifications: { def: 'g n',   run: _go('/notifications') },
    nav_settings:      { def: 'g ,',   run: _go('/settings') },
    new_movement:      { def: 'c m',   run: _go('/movements/new') },
    new_recurring:     { def: 'c r',   run: _go('/recurring/new') },
    focus_search:      { def: '/',     run: _focusSearch },
    toggle_theme:      { def: 'Alt+t', run: _toggleTheme },
  };

  // expose for the settings UI (so the action list and defaults are a single
  // source of truth — no parallel hardcoded list to drift)
  window.YN_HOTKEY_ACTIONS = YN_HOTKEY_ACTIONS;

  function _isTypingTarget(t) {
    if (!t) return false;
    if (t.isContentEditable) return true;
    var tag = (t.tagName || '').toUpperCase();
    return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT';
  }

  function _normalizeKey(e) {
    var parts = [];
    if (e.ctrlKey) parts.push('Ctrl');
    if (e.altKey)  parts.push('Alt');
    if (e.shiftKey && e.key.length !== 1) parts.push('Shift');
    if (e.metaKey) parts.push('Meta');
    var k = e.key;
    // Special case for Shift+letter: keep the lowercase letter and the Shift
    // modifier so "Ctrl+Shift+K" matches a binding string of the same shape.
    if (e.shiftKey && k.length === 1) {
      parts.push('Shift');
      k = k.toLowerCase();
    } else if (k.length === 1) {
      k = k.toLowerCase();
    }
    parts.push(k);
    return parts.join('+');
  }

  function _readBindings() {
    var b = {};
    for (var name in YN_HOTKEY_ACTIONS) b[name] = YN_HOTKEY_ACTIONS[name].def;
    try {
      var raw = document.documentElement.getAttribute('data-hotkeys-json') || '{}';
      var user = JSON.parse(raw);
      if (user && typeof user === 'object') {
        for (var k in user) {
          if (Object.prototype.hasOwnProperty.call(b, k)) {
            b[k] = String(user[k] || '');
          }
        }
      }
    } catch (_) { /* malformed JSON falls back to defaults */ }
    return b;
  }

  function _equalIgnoreCase(a, b) {
    return (a || '').toLowerCase() === (b || '').toLowerCase();
  }

  var _pendingChord = null;
  var _pendingTimer = null;
  var CHORD_TIMEOUT_MS = 1200;

  function _clearPending() {
    _pendingChord = null;
    if (_pendingTimer) { clearTimeout(_pendingTimer); _pendingTimer = null; }
  }

  function _runMatch(name, e) {
    e.preventDefault();
    e.stopPropagation();
    try { YN_HOTKEY_ACTIONS[name].run(); } catch (_) {}
  }

  function _onKeyDown(e) {
    if (document.documentElement.getAttribute('data-hotkeys-enabled') !== '1') return;
    if (_isTypingTarget(e.target)) return;
    // Allow normal copy/paste/select-all and friends to flow through
    if ((e.ctrlKey || e.metaKey) && ['a','c','v','x','z','y','f'].indexOf((e.key || '').toLowerCase()) !== -1) return;

    var k = _normalizeKey(e);
    var bindings = _readBindings();

    // 1) Resolving an in-progress chord
    if (_pendingChord) {
      var combined = _pendingChord + ' ' + k;
      var chordMatch = null;
      for (var n in bindings) {
        if (bindings[n] && _equalIgnoreCase(bindings[n], combined)) { chordMatch = n; break; }
      }
      _clearPending();
      if (chordMatch) { _runMatch(chordMatch, e); return; }
      // fall through: this key may itself be a single-key action / new chord prefix
    }

    // 2) Direct match (single key or modifier+key)
    for (var n2 in bindings) {
      var bk = bindings[n2];
      if (!bk || bk.indexOf(' ') !== -1) continue;
      if (_equalIgnoreCase(bk, k)) { _runMatch(n2, e); return; }
    }

    // 3) New chord prefix?
    for (var n3 in bindings) {
      var bk3 = bindings[n3];
      if (!bk3 || bk3.indexOf(' ') === -1) continue;
      var first = bk3.split(' ')[0];
      if (_equalIgnoreCase(first, k)) {
        _pendingChord = k;
        _pendingTimer = setTimeout(_clearPending, CHORD_TIMEOUT_MS);
        return;
      }
    }
  }

  document.addEventListener('keydown', _onKeyDown, true);

  // Helper used by the settings-page capture widget
  window.ynNormalizeKeyEvent = _normalizeKey;
})();
