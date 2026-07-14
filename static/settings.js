/**
 * Minecraft Settings V2 - Accordion appliance UI
 */
(function () {
  'use strict';

  const POLL_INTERVAL_MS = 2000;
  const MAX_POLL_ATTEMPTS = 90;

  const UI_CATEGORIES = [
    { id: 'basic', labelKey: 'cat_basic',
      keys: ['server-name'] },
  ];

  let fieldsByKey = {};
  let originalValues = {};
  let currentValues = {};
  let restarting = false;

  const $ = function (id) { return document.getElementById(id); };

  function fieldDomId(key) {
    return 'f-' + key.replace(/[^a-zA-Z0-9_-]/g, '_');
  }

  const LABEL_OVERRIDES = {
    ja: {
      'enable-lan-visibility': 'LAN公開',
      'player-idle-timeout': 'アイドル時間',
      'level-seed': 'シード',
    },
    en: {
      'enable-lan-visibility': 'LAN Discovery',
      'player-idle-timeout': 'Idle Timeout',
      'level-seed': 'Seed',
    },
  };

  function fieldLabel(field) {
    const lang = currentLang === 'ja' ? 'ja' : 'en';
    const over = LABEL_OVERRIDES[lang] && LABEL_OVERRIDES[lang][field.key];
    if (over) return over;
    return (field.label && field.label[lang]) || field.key;
  }

  function capitalize(s) { return s.charAt(0).toUpperCase() + s.slice(1); }

  function formatEnumLabel(v) {
    const key = String(v).toLowerCase();
    const known = {
      survival: 'survival', creative: 'creative', adventure: 'adventure',
      peaceful: 'peaceful', easy: 'easy', normal: 'normal', hard: 'hard',
      visitor: 'visitor', member: 'member', operator: 'operator',
      zlib: 'zlib', snappy: 'snappy',
    };
    if (known[key]) return t(known[key]) || capitalize(key);
    const translated = t(key);
    return translated !== key ? translated : capitalize(String(v));
  }

  function cloneValues(v) { return JSON.parse(JSON.stringify(v)); }

  function parseBool(v) { return String(v).toLowerCase() === 'true'; }

  function showSnackbar(msg, warn) {
    const el = $('snackbar');
    el.textContent = msg;
    el.className = warn ? 'snackbar warn' : 'snackbar';
    el.hidden = false;
    clearTimeout(showSnackbar._t);
    showSnackbar._t = setTimeout(function () { el.hidden = true; }, 4000);
  }

  function showSheet(id) {
    $(id).hidden = false;
    document.body.style.overflow = 'hidden';
  }

  function hideSheet(id) {
    $(id).hidden = true;
    if (!restarting) document.body.style.overflow = '';
  }

  function setValue(key, val) {
    currentValues[key] = val;
    updateBanners();
  }

  function hasUnsavedChanges() {
    return Object.keys(currentValues).some(function (k) {
      return String(currentValues[k]) !== String(originalValues[k]);
    });
  }

  function updateBanners() {
    const unsaved = hasUnsavedChanges();
    $('changes-banner').hidden = !unsaved || restarting;
    $('pending-banner').hidden = unsaved || !isPendingRestart() || restarting;
  }

  function setUIEnabled(on) {
    document.body.classList.toggle('ui-disabled', !on);
  }

  function showLoading() {
    restarting = true;
    setUIEnabled(false);
    $('loading-overlay').hidden = false;
    updateBanners();
  }

  function hideLoading() {
    restarting = false;
    $('loading-overlay').hidden = true;
    setUIEnabled(true);
    updateBanners();
  }

  function showInfo(field) {
    $('info-title').textContent = fieldLabel(field);
    $('info-text').textContent = fieldHint(field.key);
    showSheet('info-sheet');
  }

  function showConfirm(text, onOk) {
    $('confirm-text').textContent = text;
    showSheet('confirm-sheet');
    const ok = $('confirm-ok-btn');
    const cancel = $('confirm-cancel-btn');
    function done() {
      hideSheet('confirm-sheet');
      ok.removeEventListener('click', onOkClick);
      cancel.removeEventListener('click', onCancel);
    }
    function onOkClick() { done(); if (onOk) onOk(); }
    function onCancel() { done(); }
    ok.addEventListener('click', onOkClick);
    cancel.addEventListener('click', onCancel);
  }

  function createInfoBtn(field) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'info-btn';
    btn.textContent = 'ⓘ';
    btn.addEventListener('click', function (e) {
      e.stopPropagation();
      showInfo(field);
    });
    return btn;
  }

  function createLabel(field, text) {
    const wrap = document.createElement('div');
    wrap.className = 'cell-left';
    const label = document.createElement('span');
    label.className = 'cell-label';
    label.textContent = text || fieldLabel(field);
    wrap.appendChild(label);
    if (fieldHint(field.key)) wrap.appendChild(createInfoBtn(field));
    return wrap;
  }

  function renderSwitchCell(field) {
    const cell = document.createElement('div');
    cell.className = 'setting-cell';
    cell.appendChild(createLabel(field));
    const right = document.createElement('div');
    right.className = 'cell-right';
    const wrap = document.createElement('label');
    wrap.className = 'switch';
    const input = document.createElement('input');
    input.type = 'checkbox';
    input.id = fieldDomId(field.key);
    input.checked = parseBool(currentValues[field.key]);
    input.addEventListener('change', function (e) {
      if (field.warn_off && !e.target.checked) {
        e.target.checked = true;
        showConfirm(t('online_mode_warn_title') + '\n\n' + t('online_mode_warn'), function () {
          input.checked = false;
          setValue(field.key, 'false');
        });
        return;
      }
      setValue(field.key, e.target.checked ? 'true' : 'false');
    });
    const slider = document.createElement('span');
    slider.className = 'switch-slider';
    wrap.appendChild(input);
    wrap.appendChild(slider);
    right.appendChild(wrap);
    cell.appendChild(right);
    return cell;
  }

  function renderStepperCell(field) {
    const cell = document.createElement('div');
    cell.className = 'setting-cell';
    cell.appendChild(createLabel(field));
    const right = document.createElement('div');
    right.className = 'cell-right';
    const stepper = document.createElement('div');
    stepper.className = 'stepper';
    const min = field.min != null ? Number(field.min) : 0;
    const max = field.max != null ? Number(field.max) : 9999;
    const minus = document.createElement('button');
    minus.type = 'button';
    minus.className = 'stepper-btn';
    minus.textContent = '−';
    const val = document.createElement('span');
    val.className = 'stepper-value';
    val.id = fieldDomId(field.key) + '_val';
    val.textContent = currentValues[field.key] || min;
    const plus = document.createElement('button');
    plus.type = 'button';
    plus.className = 'stepper-btn';
    plus.textContent = '＋';
    minus.addEventListener('click', function () {
      let n = parseInt(val.textContent, 10) || min;
      n = Math.max(min, n - 1);
      val.textContent = n;
      setValue(field.key, String(n));
    });
    plus.addEventListener('click', function () {
      let n = parseInt(val.textContent, 10) || min;
      n = Math.min(max, n + 1);
      val.textContent = n;
      setValue(field.key, String(n));
    });
    stepper.appendChild(minus);
    stepper.appendChild(val);
    stepper.appendChild(plus);
    right.appendChild(stepper);
    cell.appendChild(right);
    return cell;
  }

  function renderPickerCell(field) {
    const cell = document.createElement('div');
    cell.className = 'setting-cell tappable';
    cell.appendChild(createLabel(field));
    const right = document.createElement('div');
    right.className = 'cell-right';
    const value = document.createElement('span');
    value.className = 'cell-value';
    value.id = fieldDomId(field.key);
    value.textContent = formatEnumLabel(currentValues[field.key]);
    const chev = document.createElement('span');
    chev.className = 'cell-chevron';
    chev.textContent = '›';
    right.appendChild(value);
    right.appendChild(chev);
    cell.appendChild(right);
    cell.addEventListener('click', function () { openPicker(field); });
    return cell;
  }

  function renderTextBlock(field) {
    const block = document.createElement('div');
    block.className = 'cell-block';
    block.appendChild(createLabel(field));
    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'cell-input-full';
    input.id = fieldDomId(field.key);
    input.value = currentValues[field.key] || '';
    input.addEventListener('input', function () { setValue(field.key, input.value); });
    block.appendChild(input);
    return block;
  }

  function renderSliderBlock(field) {
    const block = document.createElement('div');
    block.className = 'cell-block';
    const top = document.createElement('div');
    top.className = 'setting-cell';
    top.style.border = 'none';
    top.style.padding = '0';
    top.appendChild(createLabel(field));
    const valEl = document.createElement('span');
    valEl.className = 'cell-value';
    valEl.id = fieldDomId(field.key) + '_val';
    valEl.textContent = currentValues[field.key];
    top.appendChild(valEl);
    block.appendChild(top);
    const wrap = document.createElement('div');
    wrap.className = 'slider-wrap';
    const input = document.createElement('input');
    input.type = 'range';
    input.className = 'slider-input';
    input.id = fieldDomId(field.key);
    input.min = field.min != null ? field.min : 0;
    input.max = field.max != null ? field.max : 100;
    input.value = currentValues[field.key] || input.min;
    input.addEventListener('input', function () {
      valEl.textContent = input.value;
      setValue(field.key, input.value);
    });
    const meta = document.createElement('div');
    meta.className = 'slider-meta';
    meta.innerHTML = '<span>' + input.min + '</span><span>' + input.max + '</span>';
    wrap.appendChild(input);
    wrap.appendChild(meta);
    block.appendChild(wrap);
    return block;
  }

  function renderNumberCell(field) {
    if (field.key === 'player-idle-timeout') return renderStepperCell(field);
    const cell = document.createElement('div');
    cell.className = 'setting-cell';
    const labelText = field.key === 'server-port' ? t('port_ipv4')
      : field.key === 'server-portv6' ? t('port_ipv6') : fieldLabel(field);
    cell.appendChild(createLabel(field, labelText));
    const right = document.createElement('div');
    right.className = 'cell-right';
    const input = document.createElement('input');
    input.type = 'number';
    input.className = 'cell-input';
    input.id = fieldDomId(field.key);
    input.value = currentValues[field.key] || '';
    if (field.min != null) input.min = field.min;
    if (field.max != null) input.max = field.max;
    input.addEventListener('input', function () { setValue(field.key, input.value); });
    right.appendChild(input);
    cell.appendChild(right);
    return cell;
  }

  function renderField(field) {
    if (!field) return null;
    if (field.type === 'boolean') return renderSwitchCell(field);
    if (field.type === 'enum') return renderPickerCell(field);
    if (field.type === 'stepper' || (field.type === 'number' && field.key === 'player-idle-timeout')) {
      return renderStepperCell(field);
    }
    if (field.type === 'slider') return renderSliderBlock(field);
    if (field.type === 'number') return renderNumberCell(field);
    return renderTextBlock(field);
  }

  function renderUI() {
    const container = $('settings-fields');
    container.innerHTML = '';

    if (!Object.keys(fieldsByKey).length) {
      container.innerHTML = '<p class="settings-loading">' + t('load_error') + '</p>';
      return;
    }

    const card = document.createElement('section');
    card.className = 'card settings-card';
    const title = document.createElement('h2');
    title.className = 'card-title';
    title.textContent = t('cat_basic');
    card.appendChild(title);

    const note = document.createElement('p');
    note.className = 'card-label settings-note';
    note.textContent = t('settings_note');
    card.appendChild(note);

    UI_CATEGORIES.forEach(function (cat) {
      cat.keys.forEach(function (key) {
        const el = renderField(fieldsByKey[key]);
        if (el) card.appendChild(el);
      });
    });

    container.appendChild(card);
  }

  function openPicker(field) {
    if (restarting) return;
    $('picker-title').textContent = fieldLabel(field);
    const box = $('picker-options');
    box.innerHTML = '';
    (field.options || []).forEach(function (opt) {
      const btn = document.createElement('button');
      btn.type = 'button';
      const sel = String(currentValues[field.key]).toLowerCase() === String(opt).toLowerCase();
      btn.className = 'sheet-option' + (sel ? ' selected' : '');
      btn.textContent = formatEnumLabel(opt);
      btn.addEventListener('click', function () {
        setValue(field.key, opt);
        const el = $(fieldDomId(field.key));
        if (el) el.textContent = formatEnumLabel(opt);
        hideSheet('picker-sheet');
      });
      box.appendChild(btn);
    });
    showSheet('picker-sheet');
  }

  function syncFromApi(data) {
    fieldsByKey = {};
    const list = data.fields || [];
    if (!list.length && data.sections) {
      data.sections.forEach(function (s) {
        (s.fields || []).forEach(function (f) { list.push(f); });
      });
    }
    list.forEach(function (f) { fieldsByKey[f.key] = f; });
    originalValues = {};
    currentValues = {};
    Object.keys(fieldsByKey).forEach(function (k) {
      originalValues[k] = fieldsByKey[k].value;
      currentValues[k] = fieldsByKey[k].value;
    });
  }

  function readFromForm() {
    const properties = {};
    Object.keys(fieldsByKey).forEach(function (key) {
      const field = fieldsByKey[key];
      const id = fieldDomId(key);
      if (field.type === 'boolean') {
        const el = $(id);
        properties[key] = el && el.checked ? 'true' : 'false';
      } else if (field.type === 'stepper' || (field.type === 'number' && key === 'player-idle-timeout')) {
        const el = $(id + '_val');
        properties[key] = el ? el.textContent : currentValues[key];
      } else if (field.type === 'enum') {
        properties[key] = currentValues[key];
      } else {
        const el = $(id);
        properties[key] = el ? el.value : currentValues[key];
      }
    });
    return { properties: properties };
  }

  async function fetchServerStatus() {
    const res = await fetch('/api/server');
    const data = await res.json();
    return data.status;
  }

  async function waitForRunning() {
    for (let i = 0; i < MAX_POLL_ATTEMPTS; i++) {
      await new Promise(function (r) { setTimeout(r, POLL_INTERVAL_MS); });
      try {
        if (await fetchServerStatus() === 'running') return true;
      } catch (e) { /* retry */ }
    }
    return false;
  }

  async function performRestart() {
    showLoading();
    try {
      const res = await fetch('/api/server/restart', { method: 'POST' });
      const data = await res.json();
      if (!res.ok || !data.success) throw new Error('fail');
      const ok = await waitForRunning();
      hideLoading();
      if (ok) {
        setPendingRestart(false);
        updateBanners();
        showSnackbar(t('applied'));
      } else {
        showSnackbar(t('restart_fail'), true);
        setPendingRestart(true);
        updateBanners();
      }
    } catch (e) {
      hideLoading();
      showSnackbar(t('restart_fail'), true);
      setPendingRestart(true);
      updateBanners();
    }
  }

  async function loadSettings() {
    if (restarting) return;
    try {
      const res = await fetch('/api/settings', { cache: 'no-store' });
      if (!res.ok) throw new Error('load');
      syncFromApi(await res.json());
      renderUI();
      updateBanners();
    } catch (e) {
      $('settings-fields').innerHTML = '<p class="settings-loading">' + t('load_error') + '</p>';
    }
  }

  async function saveAndPromptRestart() {
    if (restarting) return;
    const payload = readFromForm();
    try {
      const res = await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok || !data.success) throw new Error('save');
      originalValues = cloneValues(payload.properties);
      currentValues = cloneValues(payload.properties);
      updateBanners();
      applyI18n();
      showSheet('save-restart-sheet');
    } catch (e) {
      showSnackbar(t('save_error'), true);
    }
  }

  function bindEvents() {
    $('btn-apply-changes').addEventListener('click', saveAndPromptRestart);
    $('btn-apply-now').addEventListener('click', performRestart);
    $('save-restart-ok').addEventListener('click', function () {
      hideSheet('save-restart-sheet');
      performRestart();
    });
    $('save-restart-later').addEventListener('click', function () {
      hideSheet('save-restart-sheet');
      setPendingRestart(true);
      updateBanners();
    });
    $('save-restart-backdrop').addEventListener('click', function () {
      hideSheet('save-restart-sheet');
      setPendingRestart(true);
      updateBanners();
    });
    $('picker-backdrop').addEventListener('click', function () { hideSheet('picker-sheet'); });
    $('info-backdrop').addEventListener('click', function () { hideSheet('info-sheet'); });
    $('confirm-backdrop').addEventListener('click', function () { hideSheet('confirm-sheet'); });
    $('btn-lang').addEventListener('click', function () { showSheet('lang-sheet'); });
    $('lang-backdrop').addEventListener('click', function () { hideSheet('lang-sheet'); });
    document.querySelectorAll('#lang-sheet [data-lang]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        setLang(btn.getAttribute('data-lang'));
        applyI18n();
        renderUI();
        hideSheet('lang-sheet');
      });
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    applyI18n();
    bindEvents();
    loadSettings();
  });
})();
