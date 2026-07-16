(function () {
  'use strict';

  const STATUS_ICON = {
    pass: '🟢',
    warn: '🟡',
    fail: '🔴',
    info: '🟡',
    pending: '⚪',
  };

  const DELAY_MS = 3000;
  const SERIAL_PATTERN = /^(MCS|JRT)-\d{6}$/;

  let busy = false;
  let flowPassword = '';

  const $ = function (id) { return document.getElementById(id); };

  function showSnackbar(msg) {
    const el = $('snackbar');
    el.textContent = msg;
    el.hidden = false;
    clearTimeout(showSnackbar._t);
    showSnackbar._t = setTimeout(function () { el.hidden = true; }, 3000);
  }

  function setBusy(state) {
    busy = state;
    document.body.classList.toggle('ui-disabled', state);
  }

  function statusClass(status) {
    return status === 'pass' ? 'pass'
      : status === 'warn' ? 'warn'
      : status === 'info' ? 'info'
      : status === 'pending' ? 'pending'
      : 'fail';
  }

  function renderStep(label, status, statusLabel) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'health-check-item' + (status === 'pending' ? ' pending' : ' done');
    btn.style.cursor = 'default';
    btn.innerHTML =
      '<span class="health-check-left">' +
        '<span class="health-check-icon">' + (STATUS_ICON[status] || '⚪') + '</span>' +
        '<span class="health-check-label">' + label + '</span>' +
      '</span>' +
      '<span class="health-check-right ' + statusClass(status) + '">' +
        statusLabel +
      '</span>';
    return btn;
  }

  function hideAllCards() {
    $('auth-card').hidden = true;
    $('progress-card').hidden = true;
    $('message-card').hidden = true;
    $('serial-card').hidden = true;
    $('check-card').hidden = true;
    $('result-card').hidden = true;
  }

  function showMessage(text) {
    hideAllCards();
    $('message-text').textContent = text;
    $('message-card').hidden = false;
  }

  function wait(ms) {
    return new Promise(function (resolve) { setTimeout(resolve, ms); });
  }

  async function fetchJson(url, options) {
    const res = await fetch(url, options || { cache: 'no-store' });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.message || 'リクエストに失敗しました');
    }
    return data;
  }

  async function authenticate(password) {
    return fetchJson('/api/shipment/auth', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password: password }),
    });
  }

  async function runInitStep(stepId) {
    return fetchJson('/api/shipment/init/' + stepId, { method: 'POST' });
  }

  async function runSerialUpdate(serial) {
    return fetchJson('/api/shipment/serial', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ serial: serial }),
    });
  }

  async function runFinalize() {
    return fetchJson('/api/shipment/finalize', { method: 'POST' });
  }

  async function runInitPhase(steps) {
    hideAllCards();
    $('progress-card').hidden = false;
    $('progress-title').textContent = '初期化中…';

    const list = $('step-list');
    list.innerHTML = '';
    const rows = steps.map(function (step) {
      const row = renderStep(step.label, 'pending', '待機中');
      list.appendChild(row);
      return row;
    });

    for (let i = 0; i < steps.length; i++) {
      const step = steps[i];
      const pct = Math.round((i / steps.length) * 100);
      $('progress-bar').style.width = pct + '%';
      $('progress-status').textContent = step.label + '…';
      rows[i].replaceWith(renderStep(step.label, 'pending', '実行中…'));

      const result = await runInitStep(step.id);
      if (!result.success) {
        rows[i].replaceWith(renderStep(step.label, 'fail', 'FAIL'));
        throw new Error(result.message || '初期化に失敗しました');
      }
      rows[i].replaceWith(renderStep(step.label, 'pass', '完了'));
    }

    $('progress-bar').style.width = '100%';
    $('progress-status').textContent = '初期化完了';
  }

  function normalizeSerial(value) {
    return (value || '').trim().toUpperCase().replace(/\s+/g, '');
  }

  function showSerialInput(currentSerial) {
    hideAllCards();
    $('serial-current').textContent = currentSerial || '未設定';
    $('shipment-serial').value = '';
    $('serial-error').hidden = true;
    $('serial-card').hidden = false;
    $('shipment-serial').focus();
  }

  function waitForSerialInput(currentSerial) {
    return new Promise(function (resolve, reject) {
      showSerialInput(currentSerial);

      function cleanup() {
        $('btn-serial-apply').removeEventListener('click', onApply);
        $('shipment-serial').removeEventListener('keydown', onKeydown);
      }

      async function onApply() {
        const serial = normalizeSerial($('shipment-serial').value);
        if (!SERIAL_PATTERN.test(serial)) {
          $('serial-error').textContent = 'MCS-000001 形式（6桁）で入力してください';
          $('serial-error').hidden = false;
          return;
        }
        cleanup();
        $('serial-card').hidden = true;
        resolve(serial);
      }

      function onKeydown(e) {
        if (e.key === 'Enter') onApply();
      }

      $('btn-serial-apply').addEventListener('click', onApply);
      $('shipment-serial').addEventListener('keydown', onKeydown);
    });
  }

  async function runSerialPhase(serial) {
    $('progress-card').hidden = false;
    $('progress-title').textContent = 'シリアル番号設定中…';
    $('progress-status').textContent = serial + ' を適用しています…';
    $('progress-bar').style.width = '30%';

    const serialResult = await runSerialUpdate(serial);
    if (!serialResult.success) {
      throw new Error(serialResult.message || 'シリアル番号の設定に失敗しました');
    }

    $('progress-bar').style.width = '70%';
    $('progress-status').textContent = serialResult.serial + ' を適用しました。仕上げ処理中…';

    const finalizeResult = await runFinalize();
    if (!finalizeResult.success) {
      throw new Error(finalizeResult.message || '仕上げ処理に失敗しました');
    }

    $('progress-bar').style.width = '100%';
    $('progress-status').textContent = '出荷設定が完了しました';
    await wait(800);
    $('progress-card').hidden = true;
  }

  function computeQaOverall(checks) {
    const hasFail = checks.some(function (c) {
      return c.status === 'fail' || c.status === 'warn';
    });
    return hasFail ? 'fail' : 'pass';
  }

  async function runCheckPhase() {
    hideAllCards();
    $('check-card').hidden = false;

    const defs = await fetchJson('/api/health/definitions?mode=qa');
    const items = defs.checks || [];
    const list = $('check-list');
    list.innerHTML = '';
    const collected = [];

    items.forEach(function (item) {
      list.appendChild(renderStep(item.label, 'pending', '確認中…'));
    });

    for (let i = 0; i < items.length; i++) {
      const item = items[i];
      const pct = Math.round(((i + 1) / items.length) * 100);
      $('check-progress-bar').style.width = pct + '%';
      const result = await fetchJson('/api/health/check/' + item.id);
      collected.push(result);
      const label = result.status === 'pass' ? 'PASS'
        : result.status === 'info' ? '手動'
        : result.status_label;
      list.children[i].replaceWith(renderStep(item.label, result.status, label));
    }

    $('check-card').hidden = true;
    $('result-card').hidden = false;

    const overall = computeQaOverall(collected.filter(function (c) { return c.status !== 'info'; }));
    const box = $('result-box');
    const statusEl = $('result-status');
    const errorEl = $('result-error');

    if (overall === 'pass') {
      box.className = 'qa-pass-box';
      statusEl.textContent = '出荷可能です。';
      errorEl.hidden = true;
    } else {
      box.className = 'qa-pass-box fail';
      statusEl.textContent = '出荷不可';
      const problems = collected
        .filter(function (c) { return c.status === 'fail' || c.status === 'warn'; })
        .map(function (c) { return c.label + ': ' + c.message; });
      errorEl.textContent = problems.join('\n');
      errorEl.hidden = false;
    }
  }

  async function startShipmentFlow(password) {
    if (busy) return;
    setBusy(true);
    $('auth-error').hidden = true;
    flowPassword = password;

    try {
      const auth = await authenticate(password);
      if (!auth.success) {
        $('auth-error').textContent = auth.message || '認証に失敗しました';
        $('auth-error').hidden = false;
        $('auth-card').hidden = false;
        return;
      }

      const stepsData = await fetchJson('/api/shipment/steps');
      await runInitPhase(stepsData.steps || []);

      showMessage('初期化が完了しました。');
      await wait(DELAY_MS);

      const serial = await waitForSerialInput(stepsData.current_serial);
      await runSerialPhase(serial);

      showMessage('出荷時設定が終わりました。');
      await wait(DELAY_MS);

      await runCheckPhase();
    } catch (err) {
      showSnackbar(err.message || 'エラーが発生しました');
      $('auth-error').textContent = err.message || 'エラーが発生しました';
      $('auth-error').hidden = false;
      $('auth-card').hidden = false;
      $('progress-card').hidden = false;
      $('progress-status').textContent = 'エラー: ' + (err.message || '不明なエラー');
    } finally {
      setBusy(false);
    }
  }

  function bindEvents() {
    $('btn-auth-start').addEventListener('click', function () {
      const password = ($('shipment-password').value || '').trim();
      if (!password) {
        $('auth-error').textContent = 'パスワードを入力してください';
        $('auth-error').hidden = false;
        return;
      }
      startShipmentFlow(password);
    });

    $('shipment-password').addEventListener('keydown', function (e) {
      if (e.key === 'Enter') $('btn-auth-start').click();
    });

    $('btn-back-home').addEventListener('click', function () {
      window.location.href = '/';
    });
  }

  document.addEventListener('DOMContentLoaded', bindEvents);
})();
