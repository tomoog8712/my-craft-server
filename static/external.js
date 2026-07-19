(function () {
  'use strict';

  const POLL_MS = 10000;
  const AUTH_POLL_MS = 10000;

  let pollTimer = null;
  let busy = false;
  let settingsOpen = false;

  const $ = function (id) { return document.getElementById(id); };

  function showSnackbar(msg, warn) {
    const el = $('snackbar');
    el.textContent = msg;
    el.className = warn ? 'snackbar warn' : 'snackbar';
    el.hidden = false;
    clearTimeout(showSnackbar._t);
    showSnackbar._t = setTimeout(function () { el.hidden = true; }, 4000);
  }

  function setBusy(state) {
    busy = state;
    document.body.classList.toggle('ui-disabled', state);
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

  function setMethodBadge(el, ready, readyLabel, notReadyLabel) {
    if (!el) return;
    el.textContent = ready ? '🟢 ' + readyLabel : '🔴 ' + notReadyLabel;
    el.className = 'method-state ' + (ready ? 'ready' : 'not-ready');
  }

  function hasEndpoint(data) {
    const endpoint = data.endpoint || data.address || '';
    return !!(endpoint && endpoint !== '-');
  }

  function renderPortforward(portcheck, summary) {
    const pf = summary || {};
    const ready = pf.state === 'ready';
    setMethodBadge($('pf-state-badge'), ready, '開放済み', '未開放');

    const lanIp = portcheck.lan_ip || '-';
    const publicIp = portcheck.public_ip || '-';
    const extPort = portcheck.external_port || '19132';
    const target = pf.connection_target || portcheck.connection_target || '-';

    $('pf-lan-ip').textContent = lanIp;
    $('pf-public-ip').textContent = publicIp;
    $('pf-mc-port').textContent = extPort;
    $('pf-target').textContent = target;
  }

  function renderPlayitSetup(playit) {
    const setupPhase = playit.setup_phase || 'auth';
    const showAuthStep = setupPhase === 'auth';
    const showTunnelStep = setupPhase === 'tunnel';

    $('auth-step').hidden = !showAuthStep;
    $('tunnel-step').hidden = !showTunnelStep;

    if (showAuthStep) {
      $('btn-start-auth').hidden = !!playit.claim_url;
      $('auth-panel').hidden = !playit.claim_url;

      if (playit.claim_url) {
        $('auth-url').textContent = playit.claim_url;
        $('auth-url').href = playit.claim_url;
        if (playit.qr_url) {
          $('auth-qr').src = playit.qr_url;
          $('auth-qr').hidden = false;
        } else {
          $('auth-qr').hidden = true;
        }
        if (playit.claim_agent_ready) {
          $('auth-wait-label').textContent = 'エージェント接続済み。下のリンクで認証後、この管理画面に戻ってください（Playit.ggの「Agent Setup」は閉じてOK）';
        } else if (playit.last_error) {
          $('auth-wait-label').textContent = 'エージェントを起動しています…（' + playit.last_error + '）';
        } else {
          $('auth-wait-label').textContent = 'エージェントを起動しています… 完了後、Playit.ggで認証してください';
        }
        startPoll(true);
      } else if (!playit.authenticated) {
        $('auth-panel').hidden = true;
        $('btn-start-auth').hidden = false;
        stopPoll();
      } else {
        $('auth-panel').hidden = true;
        $('btn-start-auth').hidden = true;
        startPoll();
      }
    } else if (showTunnelStep) {
      const hintEl = $('tunnel-status-msg');
      const afterHint = $('tunnel-after-create-hint');
      const hint = playit.tunnel_hint || playit.last_error || '';
      if (hintEl) {
        if (hint) {
          hintEl.textContent = hint;
          hintEl.hidden = false;
        } else {
          hintEl.textContent = '';
          hintEl.hidden = true;
        }
      }
      if (afterHint && hint) {
        afterHint.hidden = false;
      }
      startPoll(false);
    } else if (hasEndpoint(playit)) {
      stopPoll();
    } else {
      startPoll(setupPhase === 'auth');
    }
  }

  function renderPlayit(playit, summary) {
    const ps = summary || {};
    const ready = !!playit.is_ready || ps.state === 'ready';
    setMethodBadge($('playit-state-badge'), ready, '有効', '無効');

    const inSetup = settingsOpen || (
      !ready && (
        !!playit.claim_url ||
        playit.setup_phase === 'tunnel' ||
        (playit.authenticated && !hasEndpoint(playit))
      )
    );

    $('playit-ready-panel').hidden = !ready || inSetup;
    $('playit-unconfigured-panel').hidden = ready || inSetup;
    $('playit-setup-panel').hidden = !inSetup;

    if (ready && !inSetup) {
      const joinHost = playit.join_host || playit.host || (playit.endpoint || '').split(':')[0] || '-';
      const joinPort = playit.port || '-';
      const endpoint = ps.connection_target || playit.endpoint || (joinHost + ':' + joinPort);
      $('playit-address').textContent = joinHost;
      $('playit-port').textContent = String(joinPort);
      $('playit-endpoint').textContent = endpoint;
      $('playit-test-result').textContent = playit.last_test_message || '-';
      settingsOpen = false;
      stopPoll();
      return;
    }

    if (inSetup) {
      renderPlayitSetup(playit);
    } else {
      settingsOpen = false;
      stopPoll();
    }
  }

  function renderPage(data) {
    renderPlayit(data.playit || {}, data.playit_summary || {});
    renderPortforward(data.portcheck || {}, data.portforward_summary || {});
    const localPort = (data.portcheck && data.portcheck.internal_port) || data.external_port || '19132';
    const tunnelPortEl = $('tunnel-local-port');
    if (tunnelPortEl) tunnelPortEl.textContent = localPort;
  }

  async function refreshStatus(force) {
    try {
      const playitUrl = force ? '/api/playit/status?refresh=1' : '/api/playit/status';
      const [extRes, playitRes] = await Promise.all([
        fetch('/api/external', { cache: 'no-store' }),
        fetch(playitUrl, { cache: 'no-store' }),
      ]);
      if (!extRes.ok) throw new Error('HTTP ' + extRes.status);
      const data = await extRes.json();
      if (playitRes.ok) {
        data.playit = await playitRes.json();
        if (data.playit_summary) {
          const ready = !!data.playit.is_ready;
          data.playit_summary.state = ready ? 'ready' : 'not_ready';
          data.playit_summary.state_label = ready ? '有効' : '無効';
        }
      }
      renderPage(data);
    } catch (_err) {
      showSnackbar('状態の取得に失敗しました', true);
    }
  }

  async function refreshPortforward(force) {
    try {
      const url = force ? '/api/portcheck?refresh=1' : '/api/portcheck';
      const res = await fetch(url, { cache: 'no-store' });
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const portcheck = await res.json();
      const ready = portcheck.external_open === true;
      const target = portcheck.connection_target || '-';
      renderPortforward(portcheck, {
        state: ready ? 'ready' : 'not_ready',
        state_label: ready ? '開放済み' : '未開放',
        connection_target: target,
      });
      if (force) showSnackbar('接続テストを実行しました');
    } catch (_err) {
      showSnackbar('ポート開放の確認に失敗しました', true);
    }
  }

  function startPoll(authMode) {
    stopPoll();
    const interval = authMode ? AUTH_POLL_MS : POLL_MS;
    pollTimer = setInterval(function () { refreshStatus(false); }, interval);
  }

  function stopPoll() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  async function startSetup() {
    if (busy) return;
    settingsOpen = true;
    setBusy(true);
    try {
      const res = await fetch('/api/playit/login', { method: 'POST' });
      const data = await res.json();
      if (!res.ok || !data.success) {
        throw new Error(data.message || 'セットアップの開始に失敗しました');
      }
      showSnackbar('セットアップを開始しました');
      await refreshStatus(true);
      startPoll(true);
    } catch (err) {
      settingsOpen = false;
      showSnackbar(err.message || 'セットアップの開始に失敗しました', true);
    } finally {
      setBusy(false);
    }
  }

  async function startAuth() {
    if (busy) return;
    setBusy(true);
    try {
      const res = await fetch('/api/playit/login', { method: 'POST' });
      const data = await res.json();
      if (!res.ok || !data.success) {
        throw new Error(data.message || '認証の開始に失敗しました');
      }
      showSnackbar('認証URLを表示しました');
      await refreshStatus(true);
      startPoll(true);
    } catch (err) {
      showSnackbar(err.message || '認証の開始に失敗しました', true);
    } finally {
      setBusy(false);
    }
  }

  async function runTest() {
    if (busy) return;
    setBusy(true);
    $('playit-test-result').textContent = 'テスト中…';
    try {
      const res = await fetch('/api/playit/test', { method: 'POST' });
      const data = await res.json();
      if (!res.ok || !data.success) {
        throw new Error(data.message || '接続テストに失敗しました');
      }
      showSnackbar(data.message || '接続テスト成功');
      await refreshStatus(true);
    } catch (err) {
      showSnackbar(err.message || '接続テストに失敗しました', true);
      await refreshStatus(false);
    } finally {
      setBusy(false);
    }
  }

  async function disconnectPlayit() {
    if (busy) return;
    const ok = window.confirm(
      'Playitの接続を解除します。\n\n' +
      '・Agentを停止します\n' +
      '・このサーバーに保存した認証情報を削除します\n' +
      '・再度「セットアップ」から設定できます\n\n' +
      'よろしいですか？'
    );
    if (!ok) return;
    setBusy(true);
    try {
      const res = await fetch('/api/playit/disconnect', { method: 'POST' });
      const data = await res.json();
      if (!res.ok || !data.success) {
        throw new Error(data.message || '接続解除に失敗しました');
      }
      settingsOpen = false;
      showSnackbar(data.message || '接続を解除しました');
      stopPoll();
      await refreshStatus(true);
    } catch (err) {
      showSnackbar(err.message || '接続解除に失敗しました', true);
    } finally {
      setBusy(false);
    }
  }

  async function createTunnel() {
    if (busy) return;
    setBusy(true);
    try {
      const res = await fetch('/api/playit/create-tunnel', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ local_ip: '127.0.0.1' }),
      });
      const data = await res.json();
      if (!res.ok || !data.success) {
        throw new Error(data.message || 'トンネル作成に失敗しました');
      }
      showSnackbar(data.message || 'トンネルを作成しました');
      await refreshStatus(true);
    } catch (err) {
      showSnackbar(err.message || 'トンネル作成に失敗しました', true);
    } finally {
      setBusy(false);
    }
  }

  document.querySelectorAll('.btn-copy').forEach(function (btn) {
    btn.addEventListener('click', function () {
      const targetId = btn.getAttribute('data-copy');
      const el = $(targetId);
      if (el) copyText(el.textContent.trim());
    });
  });

  $('btn-start-setup').addEventListener('click', startSetup);
  $('btn-start-auth').addEventListener('click', startAuth);
  $('btn-test').addEventListener('click', runTest);
  $('btn-disconnect').addEventListener('click', disconnectPlayit);
  $('btn-create-tunnel').addEventListener('click', createTunnel);
  $('btn-refresh-tunnel').addEventListener('click', function () { refreshStatus(true); });
  $('btn-playit-settings').addEventListener('click', function () {
    settingsOpen = true;
    refreshStatus(false);
  });
  $('btn-pf-copy').addEventListener('click', function () {
    copyText($('pf-target').textContent.trim());
  });
  $('btn-pf-test').addEventListener('click', function () {
    $('pf-state-badge').textContent = 'テスト中…';
    refreshPortforward(true);
  });
  refreshStatus(false);
  window.addEventListener('beforeunload', stopPoll);
})();
