// Yfine — Import from other platforms/banks
// Progressive-disclosure UI with auto-detection.

(function() {
  const I18N = window.IMP_I18N || {};

  const els = {};
  let state = {
    preview: null,        // ImportPreviewResponse payload
    fileName: null,
    includeSet: new Set() // indices to import
  };

  function $(id) { return document.getElementById(id); }

  function init() {
    els.zone        = $('imp-upload-zone');
    els.input       = $('imp-file-input');
    els.toggleAdv   = $('imp-toggle-advanced');
    els.advPanel    = $('imp-advanced');
    els.format      = $('imp-format-select');
    els.preset      = $('imp-preset-select');
    els.loading     = $('imp-loading');
    els.panel       = $('imp-preview-panel');
    els.fname       = $('imp-filename');
    els.pbadge      = $('imp-preset-badge');
    els.fbadge      = $('imp-format-badge');
    els.rowCount    = $('imp-row-count');
    els.totalIn     = $('imp-total-in');
    els.totalOut    = $('imp-total-out');
    els.currencyBlk = $('imp-currency-block');
    els.currency    = $('imp-currency');
    els.dupSummary  = $('imp-dup-summary');
    els.dupCount    = $('imp-dup-count');
    els.dupReview   = $('imp-dup-review-link');
    els.warnings    = $('imp-warnings');
    els.targetSrc   = $('imp-target-source');
    els.newSrcForm  = $('imp-new-source-form');
    els.newSrcName  = $('imp-new-source-name');
    els.newSrcCurr  = $('imp-new-source-currency');
    els.toggleMore  = $('imp-toggle-more');
    els.morePanel   = $('imp-more');
    els.excludeStats= $('imp-exclude-stats');
    els.commitBtn   = $('imp-commit-btn');
    els.commitLabel = $('imp-commit-btn-label');
    els.cancelBtn   = $('imp-cancel-btn');
    // duplicates modal
    els.dupModalEl  = $('impDuplicatesModal');
    els.dupRows     = $('imp-dup-rows');
    els.dupSelAll   = $('imp-dup-select-all');
    els.dupDesAll   = $('imp-dup-deselect-all');
    els.dupSkipDup  = $('imp-dup-skip-duplicates');
    els.dupConfirm  = $('imp-dup-confirm');
    // mapping modal
    els.mapModalEl  = $('impMappingModal');
    els.mapFields   = $('imp-mapping-fields');
    els.mapApply    = $('imp-mapping-apply');

    if (!els.zone) return; // tab not on page

    els.zone.addEventListener('click', () => els.input.click());
    els.zone.addEventListener('dragover', (e) => { e.preventDefault(); els.zone.classList.add('bg-label-info'); });
    els.zone.addEventListener('dragleave', () => els.zone.classList.remove('bg-label-info'));
    els.zone.addEventListener('drop', (e) => {
      e.preventDefault();
      els.zone.classList.remove('bg-label-info');
      if (e.dataTransfer.files.length) runPreview(e.dataTransfer.files[0]);
    });
    els.input.addEventListener('change', (e) => {
      const f = e.target.files[0];
      if (f) runPreview(f);
      e.target.value = '';
    });

    els.toggleAdv.addEventListener('click', () => toggleCollapse(els.advPanel, els.toggleAdv));
    els.toggleMore.addEventListener('click', () => toggleCollapse(els.morePanel, els.toggleMore));

    els.targetSrc.addEventListener('change', function() {
      els.newSrcForm.style.display = this.value === '__new__' ? '' : 'none';
      if (this.value === '__new__' && !els.newSrcCurr.value) {
        const hint = state.preview && state.preview.detected_currency;
        if (hint) els.newSrcCurr.value = hint;
      }
    });

    els.cancelBtn.addEventListener('click', resetUI);
    els.commitBtn.addEventListener('click', commitImport);
    els.dupReview.addEventListener('click', openDuplicatesModal);
    els.dupSelAll.addEventListener('click', () => setAllDupCheckboxes(true));
    els.dupDesAll.addEventListener('click', () => setAllDupCheckboxes(false));
    els.dupSkipDup.addEventListener('click', skipAllDuplicates);
    els.dupConfirm.addEventListener('click', applyDuplicatesSelection);
    els.mapApply.addEventListener('click', applyMapping);
    // Filter preset dropdown by chosen format
    els.format.addEventListener('change', filterPresetsByFormat);
  }

  function toggleCollapse(panel, anchor) {
    const isOpen = panel.style.display !== 'none';
    panel.style.display = isOpen ? 'none' : '';
    const icon = anchor.querySelector('i.bi');
    if (icon) {
      icon.classList.toggle('bi-chevron-right', isOpen);
      icon.classList.toggle('bi-chevron-down', !isOpen);
    }
  }

  function filterPresetsByFormat() {
    const fmt = els.format.value;
    Array.from(els.preset.options).forEach(opt => {
      if (!opt.value) return;
      const pf = opt.getAttribute('data-format');
      opt.hidden = fmt && pf && pf !== fmt;
    });
    if (els.preset.selectedOptions[0] && els.preset.selectedOptions[0].hidden) {
      els.preset.value = '';
    }
  }

  async function runPreview(file) {
    if (!file) return;
    state.fileName = file.name;
    els.panel.style.display = 'none';
    els.loading.style.display = '';

    const fd = new FormData();
    fd.append('file', file);
    if (els.format.value) fd.append('format', els.format.value);
    if (els.preset.value)  fd.append('preset_id', els.preset.value);
    if (els.targetSrc.value && els.targetSrc.value !== '__new__') {
      fd.append('source_id', els.targetSrc.value);
    }

    try {
      const resp = await fetch('/api/imports/preview', { method: 'POST', body: fd });
      els.loading.style.display = 'none';
      if (!resp.ok) {
        await handleApiError(resp);
        return;
      }
      const data = await resp.json();
      if (data.needs_mapping) {
        openMappingModal(data.headers || [], file);
        return;
      }
      state.preview = data;
      state.includeSet = new Set(data.default_include || []);
      renderPreview();
    } catch (err) {
      els.loading.style.display = 'none';
      showToast(err.message || I18N.error, 'error');
    }
  }

  function renderPreview() {
    const d = state.preview;
    if (!d) return;
    els.fname.textContent = state.fileName || '';
    els.fbadge.textContent = (d.detected_format || '').toUpperCase();
    if (d.detected_preset) {
      els.pbadge.style.display = '';
      els.pbadge.textContent = '✓ ' + d.detected_preset.display_name;
    } else {
      els.pbadge.style.display = 'none';
    }
    els.rowCount.textContent = d.row_count;
    els.totalIn.textContent = formatAmount(d.total_in);
    els.totalOut.textContent = formatAmount(d.total_out);
    if (d.detected_currency) {
      els.currency.textContent = d.detected_currency;
      els.currencyBlk.style.display = '';
    } else {
      els.currencyBlk.style.display = 'none';
    }

    if (d.duplicate_count > 0) {
      els.dupSummary.style.display = '';
      els.dupCount.textContent = d.duplicate_count;
    } else {
      els.dupSummary.style.display = 'none';
    }

    if (d.warnings && d.warnings.length) {
      els.warnings.style.display = '';
      els.warnings.textContent = d.warnings.join(' · ');
    } else {
      els.warnings.style.display = 'none';
    }

    updateCommitLabel();
    els.panel.style.display = '';
  }

  function updateCommitLabel() {
    const n = state.includeSet.size;
    els.commitLabel.textContent = (I18N.confirmLabel || 'Import') + ' ' + n;
  }

  function formatAmount(v) {
    if (typeof v !== 'number') return v;
    return v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function openDuplicatesModal() {
    if (!state.preview) return;
    els.dupRows.innerHTML = '';
    state.preview.rows.forEach(row => {
      const tr = document.createElement('tr');
      if (row.is_duplicate) tr.classList.add('table-warning');
      const dupAttr = row.is_duplicate ? '1' : '0';
      const dupBadge = row.is_duplicate
        ? '<span class="badge bg-warning text-dark ms-1"><i class="bi bi-files"></i></span>'
        : '';
      const dirIcon = row.direction === 'in'
        ? '<i class="bi bi-arrow-down-circle text-success"></i>'
        : '<i class="bi bi-arrow-up-circle text-danger"></i>';
      tr.innerHTML = `
        <td><input type="checkbox" class="form-check-input imp-dup-cb" data-idx="${row.index}" data-dup="${dupAttr}" ${state.includeSet.has(row.index) ? 'checked' : ''}></td>
        <td class="small">${row.date}${dupBadge}</td>
        <td class="text-end">${formatAmount(row.amount)}</td>
        <td class="text-center">${dirIcon}</td>
        <td class="small">${escapeHtml(row.note || '')}</td>
      `;
      els.dupRows.appendChild(tr);
    });
    const modal = bootstrap.Modal.getOrCreateInstance(els.dupModalEl);
    modal.show();
  }

  function setAllDupCheckboxes(value) {
    document.querySelectorAll('.imp-dup-cb').forEach(cb => { cb.checked = value; });
  }

  function skipAllDuplicates() {
    // Deselect only the rows flagged as duplicates; leave the rest as-is.
    document.querySelectorAll('.imp-dup-cb').forEach(cb => {
      if (cb.dataset.dup === '1') cb.checked = false;
    });
  }

  function applyDuplicatesSelection() {
    const newSet = new Set();
    document.querySelectorAll('.imp-dup-cb').forEach(cb => {
      if (cb.checked) newSet.add(parseInt(cb.dataset.idx, 10));
    });
    state.includeSet = newSet;
    updateCommitLabel();
    bootstrap.Modal.getOrCreateInstance(els.dupModalEl).hide();
  }

  function openMappingModal(headers, file) {
    els.mapFields.innerHTML = '';
    const fields = [
      { key: 'date', label: 'Date', required: true },
      { key: 'amount', label: 'Amount', required: true },
      { key: 'amount_in', label: 'Amount In', required: false },
      { key: 'amount_out', label: 'Amount Out', required: false },
      { key: 'note', label: 'Note', required: false },
      { key: 'currency', label: 'Currency', required: false }
    ];
    fields.forEach(f => {
      const wrap = document.createElement('div');
      wrap.className = 'mb-2';
      wrap.innerHTML = `
        <label class="form-label small mb-1">${f.label}${f.required ? ' *' : ''}</label>
        <select class="form-select form-select-sm imp-map-select" data-field="${f.key}">
          <option value="">—</option>
          ${headers.map(h => `<option value="${escapeHtml(h)}">${escapeHtml(h)}</option>`).join('')}
        </select>
      `;
      els.mapFields.appendChild(wrap);
    });
    // Stash file for retry
    state.pendingMappingFile = file;
    bootstrap.Modal.getOrCreateInstance(els.mapModalEl).show();
  }

  async function applyMapping() {
    const column_map = {};
    document.querySelectorAll('.imp-map-select').forEach(sel => {
      if (sel.value) column_map[sel.dataset.field] = sel.value;
    });
    if (!column_map.date || (!column_map.amount && !(column_map.amount_in && column_map.amount_out))) {
      showToast(I18N.error, 'warning');
      return;
    }
    bootstrap.Modal.getOrCreateInstance(els.mapModalEl).hide();

    const file = state.pendingMappingFile;
    if (!file) return;
    const fd = new FormData();
    fd.append('file', file);
    if (els.format.value) fd.append('format', els.format.value);
    fd.append('options', JSON.stringify({ column_map }));

    els.loading.style.display = '';
    try {
      const resp = await fetch('/api/imports/preview', { method: 'POST', body: fd });
      els.loading.style.display = 'none';
      if (!resp.ok) { await handleApiError(resp); return; }
      const data = await resp.json();
      state.preview = data;
      state.includeSet = new Set(data.default_include || []);
      renderPreview();
    } catch (err) {
      els.loading.style.display = 'none';
      showToast(err.message || I18N.error, 'error');
    }
  }

  async function commitImport() {
    if (!state.preview) return;
    if (state.includeSet.size === 0) {
      showToast(I18N.noRows, 'warning');
      return;
    }

    const body = {
      preview_id: state.preview.preview_id,
      include_indices: Array.from(state.includeSet),
      exclude_from_stats: !!els.excludeStats.checked,
      tag_ids: []
    };

    if (els.targetSrc.value === '__new__') {
      const name = (els.newSrcName.value || '').trim();
      const ccy  = (els.newSrcCurr.value || '').trim().toUpperCase();
      if (!name || !ccy) {
        showToast(I18N.noSource, 'warning');
        return;
      }
      body.new_source = { name, currency: ccy, starting_balance: 0 };
    } else if (els.targetSrc.value) {
      body.source_id = parseInt(els.targetSrc.value, 10);
    } else {
      showToast(I18N.noSource, 'warning');
      return;
    }

    els.commitBtn.disabled = true;
    try {
      const resp = await fetch('/api/imports/commit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });
      if (!resp.ok) { await handleApiError(resp); return; }
      const data = await resp.json();
      showUndoToast(data);
      resetUI();
      setTimeout(() => location.reload(), 1500);
    } catch (err) {
      showToast(err.message || I18N.error, 'error');
    } finally {
      els.commitBtn.disabled = false;
    }
  }

  function showUndoToast(data) {
    const msg = (I18N.success || 'Imported') + ' ' + data.imported + '.';
    const host = document.getElementById('toast-host');
    if (!host) { showToast(msg, 'success'); return; }
    const el = document.createElement('div');
    el.className = 'yn-toast t-s has-meta';
    const title = escapeHtml(msg);
    const btnId = 'imp-undo-' + Date.now();
    el.innerHTML = `
      <div class="toast-badge"><i class="bi bi-check-circle"></i></div>
      <div class="toast-body">
        <div class="toast-title">${title}</div>
        <div class="toast-meta">
          <a href="javascript:void(0)" class="toast-action" id="${btnId}">${escapeHtml(I18N.undo || 'Undo')}</a>
        </div>
      </div>
      <button type="button" class="toast-close" onclick="_dismissToast(this.closest('.yn-toast'))">×</button>
      <div class="toast-progress" style="animation-duration:12000ms"></div>
    `;
    host.appendChild(el);
    requestAnimationFrame(() => requestAnimationFrame(() => el.classList.add('show')));
    setTimeout(() => { if (el.parentNode) _dismissToast(el); }, 12000);
    document.getElementById(btnId).addEventListener('click', async function(e) {
      e.preventDefault();
      try {
        const resp = await fetch('/api/imports/undo', {
          method: 'DELETE',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ undo_token: data.undo_token })
        });
        if (resp.ok) {
          showToast(I18N.undoDone || 'Undone', 'success');
          setTimeout(() => location.reload(), 800);
        } else if (resp.status === 410) {
          showToast(I18N.undoExpired || 'Expired', 'warning');
        } else {
          await handleApiError(resp);
        }
      } catch (err) {
        showToast(err.message || I18N.error, 'error');
      } finally {
        _dismissToast(el);
      }
    });
  }

  function resetUI() {
    state.preview = null;
    state.fileName = null;
    state.includeSet = new Set();
    els.panel.style.display = 'none';
    els.loading.style.display = 'none';
    els.input.value = '';
  }

  function escapeHtml(s) {
    const d = document.createElement('div');
    d.textContent = s == null ? '' : String(s);
    return d.innerHTML;
  }

  if (document.readyState !== 'loading') init();
  else document.addEventListener('DOMContentLoaded', init);
})();
