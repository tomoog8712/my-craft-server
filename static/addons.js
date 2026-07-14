(function () {
  'use strict';

  const RESTART_POLL_MS = 2000;
  const RESTART_POLL_MAX = 90;

  let addonState = null;
  let pendingDeletePackId = null;
  let busy = false;

  const $ = function (id) { return document.getElementById(id); };

  function showSnackbar(msg, warn) {
    const el = $('snackbar');
    el.textContent = msg;
    el.className = warn ? 'snackbar warn' : 'snackbar';
    el.hidden = false;
    clearTimeout(showSnackbar._t);
    showSnackbar._t = setTimeout(function () { el.hidden = true; }, 4000);
  }

  function setBusy(state, msg) {
    busy = state;
    document.body.classList.toggle('ui-disabled', state);
    $('overlay').hidden = !state;
    if (msg) $('overlay-msg').textContent = msg;
  }

  function isMobileUpload() {
    return window.matchMedia('(hover: none) and (pointer: coarse)').matches;
  }

  function applyAddonDropzoneMode() {
    const zone = $('addon-dropzone');
    if (!zone) return;
    zone.classList.toggle('mobile-upload', isMobileUpload());
  }

  async function api(method, url, body) {
    const opts = { method: method, cache: 'no-store' };
    if (body) {
      opts.headers = { 'Content-Type': 'application/json' };
      opts.body = JSON.stringify(body);
    }
    const res = await fetch(url, opts);
    const data = await res.json();
    if (!res.ok || data.success === false) {
      throw new Error(data.message || 'エラーが発生しました');
    }
    return data;
  }

  async function parseApiResponse(res) {
    const text = await res.text();
    try { return JSON.parse(text); }
    catch (e) {
      if (res.status === 413) throw new Error('ファイルが大きすぎます');
      throw new Error('サーバーでエラーが発生しました（' + res.status + '）');
    }
  }

  async function fetchServerStatus() {
    const data = await api('GET', '/api/server');
    return data.status;
  }

  async function waitForRunning() {
    for (let i = 0; i < RESTART_POLL_MAX; i++) {
      await new Promise(function (r) { setTimeout(r, RESTART_POLL_MS); });
      try { if (await fetchServerStatus() === 'running') return true; } catch (e) {}
    }
    return false;
  }

  function addonDisplayIcon() { return '📦'; }

  function renderAddonList(data) {
    const box = $('addon-list');
    const items = data.addons || [];
    if (!items.length) {
      box.innerHTML = '<p class="card-label">追加したアドオンはありません。ファイルをドロップするか選択してください。</p>';
      return;
    }
    box.innerHTML = '';
    items.forEach(function (addon) {
      const card = document.createElement('div');
      const status = addon.status || (addon.installable === false ? 'incomplete' : (addon.enabled ? 'enabled' : 'installable'));
      const incomplete = status === 'incomplete';
      const enabled = !!addon.enabled && !incomplete;
      card.className = 'addon-card' + (incomplete ? ' incomplete' : '');
      let stateHtml = '';
      if (incomplete) {
        stateHtml = '<div class="addon-card-state incomplete">🟡 追加ファイルが必要です</div>' +
          '<p class="addon-warning">このアドオンには不足しているパックがあります。必要なファイルを追加してください。</p>';
      } else if (enabled) {
        stateHtml = '<div class="addon-card-state on">🟢 有効</div>';
      } else {
        stateHtml = '<div class="addon-card-state ready">🟢 インストール可能</div>';
      }
      const toggleLabel = enabled ? 'OFF' : 'ON';
      const toggleDisabled = incomplete && !enabled;
      card.innerHTML =
        '<div class="addon-card-head"><div class="addon-card-title">' + addonDisplayIcon() + ' ' + addon.name + '</div></div>' +
        stateHtml +
        '<div class="addon-meta">' +
          '<div>Version <strong>' + (addon.version_label || '情報なし') + '</strong></div>' +
          '<div>作者 <strong>' + (addon.author || '情報なし') + '</strong></div>' +
          (incomplete ? '' : '<div>状態 <strong>' + (enabled ? '有効' : 'インストール可能') + '</strong></div>') +
        '</div>' +
        '<div class="addon-card-actions">' +
          '<button type="button" class="btn btn-primary addon-toggle"' + (toggleDisabled ? ' disabled' : '') + '>' + toggleLabel + '</button>' +
          '<button type="button" class="btn btn-outline addon-delete-btn">削除</button>' +
        '</div>';
      const toggleBtn = card.querySelector('.addon-toggle');
      if (!toggleDisabled) {
        toggleBtn.addEventListener('click', function () { requestToggleAddon(addon, !enabled); });
      }
      card.querySelector('.addon-delete-btn').addEventListener('click', function () { confirmDeleteAddon(addon); });
      box.appendChild(card);
    });
  }

  function renderAddonHistory(entries) {
    const section = $('addon-history-section');
    const box = $('addon-history-list');
    if (!entries.length) { section.hidden = true; return; }
    section.hidden = false;
    box.innerHTML = entries.map(function (item) {
      return '<div class="addon-history-item"><div class="addon-history-date">' + (item.at_label || '') + '</div><div>' + item.pack_name + ' · ' + item.action + '</div></div>';
    }).join('');
  }

  async function reloadAddons() {
    const data = await api('GET', '/api/addons');
    addonState = data;
    $('btn-addon-rollback').hidden = !data.rollback_available;
    const wc = data.world_count || 0;
    $('addons-note').textContent = 'すべてのワールド（' + wc + '件）に適用されます。変更後はサーバー再起動が必要な場合があります。';
    renderAddonList(data);
    renderAddonHistory(data.history || []);
  }

  async function openAddons() {
    applyAddonDropzoneMode();
    setBusy(true, 'アドオンを読み込み中…');
    try { await reloadAddons(); }
    catch (e) { showSnackbar(e.message, true); }
    finally { setBusy(false); }
  }

  function showCompatSheet(warnings) {
    return new Promise(function (resolve) {
      setBusy(false);
      const lines = (warnings || []).map(function (w) { return (w.name || 'アドオン') + '（' + (w.detail || '') + '）'; }).join('\n');
      $('addon-compat-text').textContent = '現在のMinecraftで正常に動作しない可能性があります。\n' + (lines ? lines + '\n\n' : '\n') + 'それでも追加しますか？';
      $('addon-compat-sheet').hidden = false;
      document.body.style.overflow = 'hidden';
      function done(v) { $('addon-compat-sheet').hidden = true; document.body.style.overflow = ''; cleanup(); resolve(v); }
      function onOk() { done(true); }
      function onCancel() { done(false); }
      function cleanup() {
        $('addon-compat-ok').removeEventListener('click', onOk);
        $('addon-compat-cancel').removeEventListener('click', onCancel);
        $('addon-compat-backdrop').removeEventListener('click', onCancel);
      }
      $('addon-compat-ok').addEventListener('click', onOk);
      $('addon-compat-cancel').addEventListener('click', onCancel);
      $('addon-compat-backdrop').addEventListener('click', onCancel);
    });
  }

  function showRestartSheet() {
    return new Promise(function (resolve) {
      setBusy(false);
      $('addon-restart-sheet').hidden = false;
      document.body.style.overflow = 'hidden';
      function done(v) { $('addon-restart-sheet').hidden = true; document.body.style.overflow = ''; cleanup(); resolve(v); }
      function onOk() { done(true); }
      function onCancel() { done(false); }
      function cleanup() {
        $('addon-restart-ok').removeEventListener('click', onOk);
        $('addon-restart-cancel').removeEventListener('click', onCancel);
        $('addon-restart-backdrop').removeEventListener('click', onCancel);
      }
      $('addon-restart-ok').addEventListener('click', onOk);
      $('addon-restart-cancel').addEventListener('click', onCancel);
      $('addon-restart-backdrop').addEventListener('click', onCancel);
    });
  }

  function showApplySheet() {
    return new Promise(function (resolve) {
      setBusy(false);
      $('addon-apply-sheet').hidden = false;
      document.body.style.overflow = 'hidden';
      function done(v) { $('addon-apply-sheet').hidden = true; document.body.style.overflow = ''; cleanup(); resolve(v); }
      function onOk() { done(true); }
      function onCancel() { done(false); }
      function cleanup() {
        $('addon-apply-ok').removeEventListener('click', onOk);
        $('addon-apply-cancel').removeEventListener('click', onCancel);
        $('addon-apply-backdrop').removeEventListener('click', onCancel);
      }
      $('addon-apply-ok').addEventListener('click', onOk);
      $('addon-apply-cancel').addEventListener('click', onCancel);
      $('addon-apply-backdrop').addEventListener('click', onCancel);
    });
  }

  function showResultSheet(data) {
    return new Promise(function (resolve) {
      setBusy(false);
      const failed = data && (data.rolled_back || data.apply_result === 'failed');
      $('addon-result-title').textContent = failed ? '適用に失敗しました' : '適用完了';
      $('addon-result-text').textContent = (data && data.message) || (failed
        ? '正常に起動できなかったため変更を元へ戻しました。ワールドは保護されています。'
        : 'アドオンを適用しました。サーバーは正常に起動しています。実際の動作はゲーム内で確認してください。');
      $('addon-result-sheet').hidden = false;
      document.body.style.overflow = 'hidden';
      function done() {
        $('addon-result-sheet').hidden = true;
        document.body.style.overflow = '';
        $('addon-result-ok').removeEventListener('click', done);
        $('addon-result-backdrop').removeEventListener('click', done);
        resolve();
      }
      $('addon-result-ok').addEventListener('click', done);
      $('addon-result-backdrop').addEventListener('click', done);
    });
  }

  async function handleApplyResult(data) {
    setBusy(false);
    await reloadAddons();
    if (!data) return;
    if (data.apply_result === 'success' || data.rolled_back || data.startup_ok === false) {
      await showResultSheet(data);
      return;
    }
    if (data.needs_restart) {
      const ok = await showRestartSheet();
      if (!ok) return;
      setBusy(true, 'サーバーを再起動しています…');
      try {
        const result = await api('POST', '/api/addons/restart');
        await handleApplyResult(result);
      } catch (e) { showSnackbar(e.message, true); setBusy(false); }
      return;
    }
    if (data.message) showSnackbar(data.message);
  }

  async function afterAddonMutation(data, message) {
    if (message && (!data || data.apply_result !== 'success')) showSnackbar(message);
    await handleApplyResult(data);
  }

  function isAddonFile(file) {
    if (!file) return false;
    const lower = (file.name || '').toLowerCase();
    if (lower.endsWith('.mcpack') || lower.endsWith('.mcaddon') || lower.endsWith('.zip')) return true;
    const type = (file.type || '').toLowerCase();
    return type === 'application/zip' || type === 'application/x-zip-compressed' || type === 'application/octet-stream';
  }

  async function uploadAddonFiles(fileList, force) {
    if (!fileList || !fileList.length) return;
    const files = Array.prototype.filter.call(fileList, isAddonFile);
    if (!files.length) { showSnackbar('.mcpack / .mcaddon / .zip のみ対応しています', true); return; }
    const form = new FormData();
    files.forEach(function (file) { form.append('files', file); });
    if (force) form.append('force', '1');
    setBusy(true, files.length > 1 ? 'アドオンを解析中…（' + files.length + '件）' : 'アドオンを解析中…');
    try {
      const res = await fetch('/api/addons/upload', { method: 'POST', body: form });
      const data = await parseApiResponse(res);
      if (res.status === 409 && data.needs_confirm) {
        setBusy(false);
        const ok = await showCompatSheet(data.warnings);
        if (!ok) return;
        return uploadAddonFiles(files, true);
      }
      if (!res.ok || !data.success) throw new Error(data.message || '追加に失敗しました');
      setBusy(false);
      showSnackbar(data.message || 'ファイルを追加しました');
      await reloadAddons();
    } catch (e) { showSnackbar(e.message, true); setBusy(false); }
  }

  async function requestToggleAddon(addon, enabled) {
    if (!addon) return;
    if (enabled && addon.status === 'incomplete') { showSnackbar('追加ファイルが必要です', true); return; }
    const ok = await showApplySheet();
    if (!ok) return;
    setBusy(true, enabled ? 'アドオンを有効化しています…' : 'アドオンを無効化しています…');
    try {
      const data = await api('POST', '/api/addons/toggle', { pack_id: addon.pack_id, enabled: enabled, restart: true });
      await afterAddonMutation(data, data.message || '更新しました');
    } catch (e) { showSnackbar(e.message, true); setBusy(false); }
  }

  function confirmDeleteAddon(addon) {
    pendingDeletePackId = addon.pack_id;
    $('addon-delete-title').textContent = addon.name + ' を削除';
    $('addon-delete-text').textContent = addon.name + ' を削除します。すべてのワールドで使用できなくなります。';
    $('addon-delete-sheet').hidden = false;
    document.body.style.overflow = 'hidden';
  }

  async function deleteAddonConfirmed() {
    if (!pendingDeletePackId) return;
    const packId = pendingDeletePackId;
    pendingDeletePackId = null;
    $('addon-delete-sheet').hidden = true;
    document.body.style.overflow = '';
    const ok = await showApplySheet();
    if (!ok) return;
    setBusy(true, '削除中…');
    try {
      const data = await api('POST', '/api/addons/delete', { pack_id: packId, restart: true });
      await afterAddonMutation(data, data.message || '削除しました');
    } catch (e) { showSnackbar(e.message, true); setBusy(false); }
  }

  async function rollbackAddons() {
    const ok = await showConfirm('直前のバックアップに戻しますか？', '元に戻す');
    if (!ok) return;
    const applyOk = await showApplySheet();
    if (!applyOk) return;
    setBusy(true, '復元中…');
    try {
      const data = await api('POST', '/api/addons/rollback', { restart: true });
      await afterAddonMutation(data, data.message || '元に戻しました');
    } catch (e) { showSnackbar(e.message, true); setBusy(false); }
  }

  function showConfirm(text, okLabel) {
    return new Promise(function (resolve) {
      $('confirm-text').textContent = text;
      $('confirm-ok').textContent = okLabel || 'OK';
      $('confirm-sheet').hidden = false;
      document.body.style.overflow = 'hidden';
      function done(v) {
        $('confirm-sheet').hidden = true;
        document.body.style.overflow = '';
        $('confirm-ok').removeEventListener('click', onOk);
        $('confirm-cancel').removeEventListener('click', onCancel);
        $('confirm-backdrop').removeEventListener('click', onCancel);
        resolve(v);
      }
      function onOk() { done(true); }
      function onCancel() { done(false); }
      $('confirm-ok').addEventListener('click', onOk);
      $('confirm-cancel').addEventListener('click', onCancel);
      $('confirm-backdrop').addEventListener('click', onCancel);
    });
  }

  function setupAddonDropZone() {
    const zone = $('addon-dropzone');
    if (!zone) return;
    let depth = 0;
    zone.addEventListener('dragenter', function (e) {
      e.preventDefault();
      if (isMobileUpload()) return;
      depth += 1;
      zone.classList.add('drag-over');
    });
    zone.addEventListener('dragleave', function (e) {
      e.preventDefault();
      depth -= 1;
      if (depth <= 0) { depth = 0; zone.classList.remove('drag-over'); }
    });
    zone.addEventListener('dragover', function (e) { e.preventDefault(); });
    zone.addEventListener('drop', function (e) {
      e.preventDefault();
      depth = 0;
      zone.classList.remove('drag-over');
      if (isMobileUpload()) return;
      uploadAddonFiles(e.dataTransfer.files, false);
    });
  }

  function bindEvents() {
    $('btn-addon-file').addEventListener('click', function () {
      const input = $('addon-input');
      input.value = '';
      input.click();
    });
    $('btn-addon-rollback').addEventListener('click', rollbackAddons);
    $('addon-delete-cancel').addEventListener('click', function () {
      pendingDeletePackId = null;
      $('addon-delete-sheet').hidden = true;
      document.body.style.overflow = '';
    });
    $('addon-delete-backdrop').addEventListener('click', function () {
      pendingDeletePackId = null;
      $('addon-delete-sheet').hidden = true;
      document.body.style.overflow = '';
    });
    $('addon-delete-ok').addEventListener('click', deleteAddonConfirmed);
    $('addon-input').addEventListener('change', async function (e) {
      await uploadAddonFiles(e.target.files, false);
      e.target.value = '';
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    bindEvents();
    setupAddonDropZone();
    applyAddonDropzoneMode();
    openAddons();
  });
})();
