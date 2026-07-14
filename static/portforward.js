(function () {
  'use strict';

  const $ = function (id) { return document.getElementById(id); };

  function showSnackbar(msg, warn) {
    const el = $('snackbar');
    el.textContent = msg;
    el.className = warn ? 'snackbar warn' : 'snackbar';
    el.hidden = false;
    clearTimeout(showSnackbar._t);
    showSnackbar._t = setTimeout(function () { el.hidden = true; }, 4000);
  }

  function copyText(text) {
    if (!text || text === '-') return;
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () {
        showSnackbar('コピーしました');
      }).catch(function () {
        showSnackbar('コピーに失敗しました', true);
      });
      return;
    }
    showSnackbar('コピーに対応していません', true);
  }

  function fillPage(data) {
    const lanIp = data.lan_ip || '-';
    const publicIp = data.public_ip || '-';
    const extPort = data.external_port || '19132';
    const intPort = data.internal_port || extPort;
    const target = data.connection_target || (publicIp !== '-' ? publicIp + ':' + extPort : '-');
    const ready = data.external_open === true;

    $('pf-lan-ip').textContent = lanIp;
    $('pf-public-ip').textContent = publicIp;
    $('pf-mc-port').textContent = extPort;
    $('pf-target').textContent = target;
    $('pf-status').textContent = ready ? '🟢 接続可能' : '🔴 未設定';

    $('pf-port-note').textContent = extPort;
    $('pf-ext-port-step').textContent = extPort;
    $('pf-lan-step').textContent = lanIp;
    $('pf-int-port-step').textContent = intPort;
    $('pf-iphone-port').textContent = extPort;
  }

  async function loadStatus(refresh) {
    try {
      const url = refresh ? '/api/portcheck?refresh=1' : '/api/portcheck';
      const res = await fetch(url, { cache: 'no-store' });
      if (!res.ok) throw new Error('HTTP ' + res.status);
      fillPage(await res.json());
      if (refresh) showSnackbar('接続テストを実行しました');
    } catch (err) {
      showSnackbar('状態の取得に失敗しました', true);
    }
  }

  document.querySelectorAll('.btn-copy').forEach(function (btn) {
    btn.addEventListener('click', function () {
      const el = $(btn.getAttribute('data-copy'));
      if (el) copyText(el.textContent.trim());
    });
  });

  $('btn-pf-copy').addEventListener('click', function () {
    copyText($('pf-target').textContent.trim());
  });
  $('btn-pf-test').addEventListener('click', function () {
    $('pf-status').textContent = 'テスト中…';
    loadStatus(true);
  });

  loadStatus(false);
})();
