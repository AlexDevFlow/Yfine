/* Yfine — math expressions inside amount fields.
 *
 * Any input marked with `data-money` (or having class `yn-money`) becomes
 * arithmetic-aware: the user can type `100+25*1.22` and a small "= 152.50"
 * preview appears below; pressing Enter (or blurring the field) replaces the
 * expression with the computed number.
 *
 * Plain numbers behave normally — the helper only kicks in when the value
 * contains an operator, so users who just type "42" see no UI change.
 *
 * Safety: only `0-9 . , + - * / ( ) space` are accepted. Anything else marks
 * the preview as invalid and disables Apply. The evaluation goes through
 * `Function(...)` after that whitelist check, which is conceptually `eval`
 * but on a constrained character set is safe.
 */
(function() {
  'use strict';

  var SAFE_RE = /^[\d\s+\-*/().,]+$/;
  var HAS_OP_RE = /[+\-*/()]/;

  function _evaluate(expr) {
    var s = String(expr || '').trim();
    if (!s) return null;
    if (!SAFE_RE.test(s)) return null;
    // Convert decimal commas to dots so "1,5+2" works in IT/ES locales
    s = s.replace(/,/g, '.');
    try {
      // Force numeric context with a unary plus so Function returns a number,
      // not a string concatenation — and short-circuit on NaN/Infinity.
      var v = Function('"use strict"; return (' + s + ');')();
      if (typeof v !== 'number' || !isFinite(v)) return null;
      return v;
    } catch (_) {
      return null;
    }
  }

  function _format(n) {
    // Trim trailing zeros but cap at 6 decimals to keep the preview readable
    var rounded = Math.round(n * 1e6) / 1e6;
    return String(rounded);
  }

  function _attach(input) {
    if (input._ynMathBound) return;
    input._ynMathBound = true;

    // type=number rejects letters but accepts digits & a single decimal point;
    // it cannot hold an expression like "1+2". Switch to text and keep the
    // numeric keypad on mobile via inputmode=decimal.
    if (input.type === 'number') {
      input.type = 'text';
      if (!input.getAttribute('inputmode')) input.setAttribute('inputmode', 'decimal');
    }

    var preview = document.createElement('small');
    preview.className = 'yn-math-preview text-muted d-block mt-1';
    preview.style.display = 'none';
    if (input.parentNode) input.parentNode.insertBefore(preview, input.nextSibling);

    function _update() {
      var v = input.value;
      preview.style.display = 'none';
      preview.classList.remove('text-danger', 'text-success');
      input._ynComputed = null;
      if (!v || !HAS_OP_RE.test(v)) return;
      var result = _evaluate(v);
      if (result === null) {
        preview.textContent = '= —';
        preview.classList.add('text-danger');
        preview.style.display = '';
        return;
      }
      preview.textContent = '= ' + _format(result);
      preview.classList.add('text-success');
      preview.style.display = '';
      input._ynComputed = result;
    }

    function _apply() {
      if (input._ynComputed != null) {
        input.value = _format(input._ynComputed);
        preview.style.display = '';
        preview.textContent = '✓ ' + _format(input._ynComputed);
        preview.classList.remove('text-danger');
        preview.classList.add('text-success');
        // Fade out the confirmation after a beat so the field feels normal again
        setTimeout(function() {
          preview.style.display = 'none';
          preview.classList.remove('text-success');
        }, 1200);
        // Notify any listeners that the value changed (Bootstrap form
        // validators / reactive code attached to `input`)
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.dispatchEvent(new Event('change', { bubbles: true }));
      }
    }

    input.addEventListener('input', _update);
    input.addEventListener('keydown', function(e) {
      if (e.key === 'Enter') {
        if (input._ynComputed != null) {
          e.preventDefault();
          _apply();
        }
      }
    });
    input.addEventListener('blur', function() {
      if (input._ynComputed != null) {
        _apply();
        return;
      }
      // No expression in play — but switching from type=number to type=text
      // means a plain "100,50" no longer normalizes automatically. Convert a
      // single decimal comma between digits to a dot so backend parsing
      // (parseFloat / Pydantic) keeps working in IT/ES/UK-style locales.
      var v = input.value;
      if (/^-?\d+,\d+$/.test(v)) {
        input.value = v.replace(',', '.');
      }
    });

    _update();
  }

  function _scan(root) {
    var nodes = (root || document).querySelectorAll('input[data-money], input.yn-money');
    Array.prototype.forEach.call(nodes, _attach);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function() { _scan(); });
  } else {
    _scan();
  }

  // Re-scan when modals / dynamic content insert new inputs
  var _mo = new MutationObserver(function(muts) {
    for (var i = 0; i < muts.length; i++) {
      for (var j = 0; j < muts[i].addedNodes.length; j++) {
        var n = muts[i].addedNodes[j];
        if (n && n.nodeType === 1) {
          if (n.matches && (n.matches('input[data-money]') || n.matches('input.yn-money'))) {
            _attach(n);
          } else if (n.querySelectorAll) {
            _scan(n);
          }
        }
      }
    }
  });
  _mo.observe(document.body, { childList: true, subtree: true });

  // Expose for tests / debugging
  window.ynMathEvaluate = _evaluate;
})();
