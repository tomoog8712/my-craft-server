(function () {
  'use strict';

  const STATUS_ICON = {
    pass: '🟢',
    warn: '🟡',
    fail: '🔴',
    info: '🟡',
    pending: '⚪',
  };

  let running = false;
  let currentMode = 'normal';
  let collectedChecks = [];
  let reportMeta = null;

  const $ = function (id) { return document.getElementById(id); };

  function showSnackbar(msg) {
    const el = $('snackbar');
    el.textContent = msg;
    el.hidden = false;
    clearTimeout(showSnackbar._t);
    showSnackbar._t = setTimeout(function () { el.hidden = true; }, 3000);
  }

  function showSheet(id) {
    $(id).hidden = false;
    document.body.style.overflow = 'hidden';
  }

  function hideSheet(id) {
    $(id).hidden = true;
    if (!running) document.body.style.overflow = '';
  }

  function setBusy(state) {
    running = state;
    document.body.classList.toggle('ui-disabled', state);
  }

  function statusClass(status) {
    return status === 'pass' ? 'pass'
      : status === 'warn' ? 'warn'
      : status === 'info' ? 'info'
      : status === 'pending' ? 'pending'
      : 'fail';
  }

  function renderCheckButton(check, clickable) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'health-check-item' + (check.status === 'pending' ? ' pending' : '');
    btn.innerHTML =
      '<span class="health-check-left">' +
        '<span class="health-check-icon">' + (STATUS_ICON[check.status] || '⚪') + '</span>' +
        '<span class="health-check-label">' + check.label + '</span>' +
      '</span>' +
      '<span class="health-check-right ' + statusClass(check.status) + '">' +
        (check.status === 'pending' ? '確認中…' : check.status_label) +
      '</span>';
    if (clickable && check.status !== 'pending') {
      btn.addEventListener('click', function () { showDetail(check); });
    } else {
      btn.style.cursor = 'default';
    }
    return btn;
  }

  let currentDetailText = '';

  function showDetail(check) {
    $('detail-title').textContent = check.label;
    const statusEl = $('detail-status');
    statusEl.textContent = check.status_label + ' — ' + check.message;
    statusEl.className = 'detail-status ' + statusClass(check.status);
    $('detail-body').textContent = check.detail || check.message;
    $('detail-remedy').textContent = check.remedy || '特になし';
    currentDetailText = [
      check.label,
      check.status_label + ' — ' + check.message,
      '',
      check.detail || check.message,
      '',
      '対処方法',
      check.remedy || '特になし',
    ].join('\n');
    showSheet('detail-sheet');
  }

  function buildLiveList(definitions) {
    const box = $('live-check-list');
    box.innerHTML = '';
    definitions.forEach(function (def) {
      box.appendChild(renderCheckButton({
        id: def.id,
        label: def.label,
        status: 'pending',
        status_label: '確認中…',
      }, false));
    });
  }

  function updateLiveItem(check, index) {
    const box = $('live-check-list');
    const btn = box.children[index];
    if (!btn) return;
    const next = renderCheckButton(check, false);
    box.replaceChild(next, btn);
  }

  function computeOverall(checks) {
    const hasFail = checks.some(function (c) { return c.status === 'fail'; });
    const hasWarn = checks.some(function (c) { return c.status === 'warn'; });
    if (hasFail) return { status: 'fail', icon: '🔴', text: '修正が必要です' };
    if (hasWarn) return { status: 'warn', icon: '🟡', text: '注意があります' };
    return { status: 'pass', icon: '🟢', text: '問題ありません' };
  }

  function copyToClipboard(text) {
    if (!text) return Promise.reject(new Error('empty'));
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text);
    }
    return new Promise(function (resolve, reject) {
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.setAttribute('readonly', '');
      ta.style.position = 'fixed';
      ta.style.top = '0';
      ta.style.left = '0';
      ta.style.width = '100%';
      ta.style.height = '100px';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.focus();
      ta.select();
      ta.setSelectionRange(0, text.length);
      try {
        const ok = document.execCommand('copy');
        document.body.removeChild(ta);
        if (ok) resolve();
        else reject(new Error('execCommand failed'));
      } catch (err) {
        document.body.removeChild(ta);
        reject(err);
      }
    });
  }

  function showReportSheet(text) {
    $('report-text').value = text;
    showSheet('report-sheet');
  }

  function renderResults(checks, mode) {
    const overall = computeOverall(checks);
    const overallBox = $('overall-box');
    overallBox.className = 'health-overall ' + overall.status;
    $('overall-icon').textContent = overall.icon;
    $('overall-text').textContent = overall.text;

    const box = $('result-check-list');
    box.innerHTML = '';
    checks.forEach(function (check) {
      box.appendChild(renderCheckButton(check, true));
    });

    $('result-card').hidden = false;

    if (mode === 'qa') {
      $('qa-result-card').hidden = false;
      const qaBox = $('qa-pass-box');
      const qaStatus = $('qa-pass-status');
      if (overall.status === 'fail') {
        qaBox.className = 'qa-pass-box fail';
        qaStatus.textContent = 'FAIL';
      } else {
        qaBox.className = 'qa-pass-box';
        qaStatus.textContent = 'PASS';
      }
    } else {
      $('qa-result-card').hidden = true;
    }
  }

  function buildReportText(checks, meta) {
    const overall = computeOverall(checks);
    const overallLabel = overall.status === 'pass' ? 'PASS' : overall.status.toUpperCase();
    const now = new Date().toISOString();

    const keyMap = {
      lan: 'LAN', mdns: 'mDNS', api: 'API', webui: 'WebUI', nginx: 'Nginx',
      minecraft: 'Bedrock', qa_server: 'Bedrock', ssd: 'SSD',
      memory: 'Memory', cpu: 'CPU', port: 'ポート',
      server_properties: 'server.properties', internet: 'インターネット',
      internet: 'インターネット',
      playit: 'Playit.gg',
      external_port: 'ポート開放',
      version: '最新版確認', logs: 'ログ', ubuntu: 'Ubuntu',
    };

    const lines = [
      '========================================',
      'My Craft Server 診断レポート',
      '========================================',
      '診断日時 ' + now,
      '製品ID ' + (meta.product_id || '-'),
      'OS ' + (meta.os || '-'),
      'Minecraft ' + (meta.minecraft_version || '-'),
      'ホスト名 ' + (meta.hostname || '-'),
      'LAN IP ' + (meta.lan_ip || '-'),
      'ポート UDP ' + (meta.minecraft_port || '-'),
      'サーバー名 ' + (meta.server_name || '-'),
      'ワールド ' + (meta.world_name || '-'),
      '稼働時間 ' + (meta.uptime || '-'),
      '',
      '--- サマリー ---',
    ];

    checks.forEach(function (check) {
      const label = keyMap[check.id] || check.label;
      let value;
      if (check.id === 'ssd' || check.id === 'memory' || check.id === 'cpu') {
        value = check.value || check.status_label;
      } else {
        value = check.status === 'pass' ? 'PASS' : check.status_label;
      }
      lines.push(label + ' ' + value);
    });
    lines.push('総合 ' + overallLabel);
    lines.push('');
    lines.push('--- 詳細 ---');

    checks.forEach(function (check) {
      lines.push('[' + check.label + '] ' + check.status_label);
      lines.push('  ' + (check.message || ''));
      if (check.value) lines.push('  値: ' + check.value);
      const detail = (check.detail || '').trim();
      if (detail) {
        detail.split('\n').forEach(function (dl) { lines.push('  ' + dl); });
      }
    });

    lines.push('');
    lines.push('--- サービス状態 ---');
    lines.push('bedrock ' + (meta.bedrock_active ? 'active' : 'inactive'));
    lines.push('mhserver-web ' + (meta.webui_active ? 'active' : 'inactive'));
    lines.push('nginx ' + (meta.nginx_active ? 'active' : 'inactive'));
    lines.push('グローバルIP ' + (meta.public_ip || '-'));
    lines.push('SSD使用 ' + (meta.disk_used_pct != null ? meta.disk_used_pct : '-') + '% / 空き ' + (meta.disk_free_pct != null ? meta.disk_free_pct : '-') + '%');
    lines.push('メモリ ' + (meta.memory_used_pct != null ? meta.memory_used_pct : '-') + '% (' + (meta.memory_avail_mb || '-') + 'MB空き)');
    lines.push('CPU ' + (meta.cpu_used_pct != null ? meta.cpu_used_pct : '-') + '%');
    lines.push('');
    lines.push('--- サポート用ログ ---');
    lines.push(meta.support_logs || '(ログなし)');
    return lines.join('\n');
  }

  async function fetchJson(url) {
    const res = await fetch(url, { cache: 'no-store' });
    if (!res.ok) throw new Error('request failed');
    return res.json();
  }

  async function runDiagnosis(mode) {
    if (running) return;
    currentMode = mode;
    collectedChecks = [];
    reportMeta = null;

    $('start-card').hidden = true;
    $('result-card').hidden = true;
    $('qa-result-card').hidden = true;
    $('progress-card').hidden = false;
    $('progress-title').textContent = mode === 'qa' ? '出荷前テスト実行中…' : '診断中…';
    $('progress-bar').style.width = '0%';
    setBusy(true);

    try {
      const defs = await fetchJson('/api/health/definitions?mode=' + mode);
      const items = defs.checks || [];
      buildLiveList(items);

      for (let i = 0; i < items.length; i++) {
        const item = items[i];
        const pct = Math.round(((i + 1) / items.length) * 100);
        $('progress-bar').style.width = pct + '%';
        const result = await fetchJson('/api/health/check/' + item.id);
        collectedChecks.push(result);
        updateLiveItem(result, i);
      }

      reportMeta = await fetchJson('/api/health/meta');
      $('progress-card').hidden = true;
      renderResults(collectedChecks, mode);
      $('start-card').hidden = false;
    } catch (e) {
      showSnackbar('診断に失敗しました');
      $('progress-card').hidden = true;
      $('start-card').hidden = false;
    } finally {
      setBusy(false);
    }
  }

  async function copyReport() {
    if (!collectedChecks.length) return;
    const text = buildReportText(collectedChecks, reportMeta || {});
    try {
      await copyToClipboard(text);
      showSnackbar('診断レポートをコピーしました');
    } catch (e) {
      showReportSheet(text);
      showSnackbar('テキストを表示しました。長押しでコピーできます');
    }
  }

  async function copyDetail() {
    if (!currentDetailText) return;
    try {
      await copyToClipboard(currentDetailText);
      showSnackbar('コピーしました');
    } catch (e) {
      showReportSheet(currentDetailText);
      showSnackbar('テキストを表示しました。長押しでコピーできます');
    }
  }

  function resetView() {
    collectedChecks = [];
    reportMeta = null;
    $('result-card').hidden = true;
    $('qa-result-card').hidden = true;
    $('progress-card').hidden = true;
    $('start-card').hidden = false;
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  function bindEvents() {
    $('btn-start-check').addEventListener('click', function () { runDiagnosis('normal'); });
    $('btn-qa-check').addEventListener('click', function () { runDiagnosis('qa'); });
    $('btn-copy-report').addEventListener('click', copyReport);
    $('btn-rerun').addEventListener('click', resetView);
    $('detail-copy').addEventListener('click', copyDetail);
    $('detail-close').addEventListener('click', function () { hideSheet('detail-sheet'); });
    $('detail-backdrop').addEventListener('click', function () { hideSheet('detail-sheet'); });
    $('report-copy-retry').addEventListener('click', function () {
      const text = $('report-text').value;
      copyToClipboard(text).then(function () {
        showSnackbar('コピーしました');
      }).catch(function () {
        $('report-text').focus();
        $('report-text').select();
        showSnackbar('選択しました。長押しでコピーしてください');
      });
    });
    $('report-close').addEventListener('click', function () { hideSheet('report-sheet'); });
    $('report-backdrop').addEventListener('click', function () { hideSheet('report-sheet'); });
  }

  document.addEventListener('DOMContentLoaded', bindEvents);
})();
