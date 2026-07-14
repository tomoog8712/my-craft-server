(function () {
  'use strict';

  const STEP_ORDER = ['backup', 'download', 'install', 'start'];
  const CONFIRM_TEXT =
    'Minecraftを最新版へ更新します。\n\n' +
    '更新前に自動バックアップを作成します。\n' +
    'アップデート後はサーバーが再起動します。\n\n' +
    '古いMinecraftアプリでは接続できなくなる場合があります。\n\n' +
    '続行しますか？';

  let pollTimer = null;
  let busy = false;

  const $ = function (id) { return document.getElementById(id); };

  function setBusy(state) {
    busy = state;
    document.body.classList.toggle('ui-disabled', state);
    $('btn-update').disabled = state || $('btn-update').dataset.ready !== '1';
  }

  function showSheet(id) {
    $(id).hidden = false;
    document.body.style.overflow = 'hidden';
  }

  function hideSheet(id) {
    $(id).hidden = true;
    document.body.style.overflow = '';
  }

  function showConfirm(text, onOk) {
    $('confirm-text').textContent = text;
    showSheet('confirm-sheet');
    const okBtn = $('confirm-ok');
    const cancelBtn = $('confirm-cancel');
    function cleanup() {
      hideSheet('confirm-sheet');
      okBtn.removeEventListener('click', onOkClick);
      cancelBtn.removeEventListener('click', onCancel);
    }
    function onOkClick() { cleanup(); if (onOk) onOk(); }
    function onCancel() { cleanup(); }
    okBtn.addEventListener('click', onOkClick);
    cancelBtn.addEventListener('click', onCancel);
    $('confirm-backdrop').onclick = onCancel;
  }

  function updateSteps(activeStep) {
    const activeIndex = STEP_ORDER.indexOf(activeStep);
    document.querySelectorAll('.step-item').forEach(function (el) {
      const step = el.getAttribute('data-step');
      const idx = STEP_ORDER.indexOf(step);
      el.classList.remove('active', 'done');
      if (idx < activeIndex) el.classList.add('done');
      if (idx === activeIndex) el.classList.add('active');
    });
  }

  function renderHistory(history) {
    const box = $('history-list');
    if (!history || !history.length) {
      box.innerHTML = '<p class="card-label">履歴はありません</p>';
      return;
    }
    box.innerHTML = history.map(function (item) {
      const cls = item.success ? 'ok' : 'ng';
      return (
        '<div class="history-item">' +
          '<div class="date">' + item.date + '</div>' +
          '<div class="versions">' + item.from_version + ' → ' + item.to_version + '</div>' +
          '<div class="result ' + cls + '">' + item.status_label + '</div>' +
        '</div>'
      );
    }).join('');
  }

  function renderInfo(data) {
    $('current-version').textContent = data.current_version || '-';
    $('latest-version').textContent = data.latest_version || '-';
    const status = $('update-status');
    status.textContent = data.status_label || '確認中…';
    status.className = 'status-pill ' + (data.has_update ? 'warn' : 'ok');
    const btn = $('btn-update');
    btn.dataset.ready = data.has_update ? '1' : '0';
    btn.disabled = !data.has_update || busy;
    renderHistory(data.history || []);
  }

  async function loadInfo() {
    const res = await fetch('/api/update/info');
    const data = await res.json();
    renderInfo(data);
  }

  async function pollStatus() {
    try {
      const res = await fetch('/api/update/status');
      const data = await res.json();
      const state = data.state || 'idle';

      if (state === 'running' || state === 'restoring') {
        $('update-overlay').hidden = false;
        $('overlay-title').textContent = state === 'restoring'
          ? 'バックアップから復元しています'
          : 'Minecraftを更新しています';
        updateSteps(data.step === 'stop' ? 'backup' : (data.step || 'backup'));
        $('overlay-message').textContent = data.message || 'しばらくお待ちください…';
        setBusy(true);
        return;
      }

      $('update-overlay').hidden = true;
      setBusy(false);

      if (state === 'done') {
        stopPolling();
        $('done-text').textContent =
          '現在のバージョン\n' + (data.current_version || '-') +
          '\n\n設定・ワールドは維持されています。';
        showSheet('done-sheet');
        loadInfo();
        return;
      }

      if (state === 'error') {
        stopPolling();
        $('error-text').textContent = data.message || 'バックアップから復元しました。';
        showSheet('error-sheet');
        loadInfo();
        return;
      }

      stopPolling();
    } catch (e) {
      /* keep polling */
    }
  }

  function startPolling() {
    stopPolling();
    pollTimer = setInterval(pollStatus, 2000);
    pollStatus();
  }

  function stopPolling() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = null;
  }

  async function startUpdate() {
    setBusy(true);
    $('update-overlay').hidden = false;
    updateSteps('backup');
    $('overlay-message').textContent = 'アップデートを開始しています…';
    try {
      const res = await fetch('/api/update/start', { method: 'POST' });
      const data = await res.json();
      if (!res.ok || !data.success) throw new Error(data.message || 'start failed');
      startPolling();
    } catch (e) {
      setBusy(false);
      $('update-overlay').hidden = true;
      alert('アップデートを開始できませんでした: ' + e.message);
    }
  }

  function bindEvents() {
    $('btn-update').addEventListener('click', function () {
      if (busy) return;
      showConfirm(CONFIRM_TEXT, startUpdate);
    });
    $('done-close').addEventListener('click', function () { hideSheet('done-sheet'); });
    $('error-close').addEventListener('click', function () { hideSheet('error-sheet'); });
    $('done-backdrop').addEventListener('click', function () { hideSheet('done-sheet'); });
    $('error-backdrop').addEventListener('click', function () { hideSheet('error-sheet'); });
  }

  document.addEventListener('DOMContentLoaded', function () {
    bindEvents();
    loadInfo();
    pollStatus().then(function () {
      const res = fetch('/api/update/status').then(function (r) { return r.json(); }).then(function (d) {
        if (d.state === 'running' || d.state === 'restoring') startPolling();
      });
      return res;
    });
    setInterval(loadInfo, 60000);
  });
})();
