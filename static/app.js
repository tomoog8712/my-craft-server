/**
 * My Craft Server - Dashboard with server control & copy
 */

const POLL_INTERVAL = 10000;
let isOperating = false;

function setStatusDot(el, running) {
  el.classList.remove('running', 'stopped');
  el.classList.add(running ? 'running' : 'stopped');
}

function showToast(text, isError) {
  const toast = document.getElementById('toast');
  toast.textContent = text;
  toast.classList.toggle('error', !!isError);
  toast.hidden = false;
  setTimeout(function () { toast.hidden = true; }, isError ? 4000 : 2000);
}

function showActionMsg(text, success) {
  const el = document.getElementById('server-action-msg');
  el.textContent = text;
  el.classList.toggle('success', success);
  el.classList.toggle('error', !success);
  el.hidden = false;
  setTimeout(function () { el.hidden = true; }, 4000);
}

function setButtonsLoading(loading) {
  ['btn-start', 'btn-stop', 'btn-restart'].forEach(function (id) {
    const btn = document.getElementById(id);
    if (!btn) return;
    btn.disabled = loading;
    btn.classList.toggle('loading', loading);
  });
}

function showConfirm(message) {
  return new Promise(function (resolve) {
    const modal = document.getElementById('confirm-modal');
    const msgEl = document.getElementById('confirm-message');
    const okBtn = document.getElementById('confirm-ok');
    const cancelBtn = document.getElementById('confirm-cancel');
    const backdrop = document.getElementById('confirm-backdrop');

    msgEl.textContent = message;
    modal.hidden = false;

    function cleanup(result) {
      modal.hidden = true;
      okBtn.removeEventListener('click', onOk);
      cancelBtn.removeEventListener('click', onCancel);
      backdrop.removeEventListener('click', onCancel);
      resolve(result);
    }

    function onOk() { cleanup(true); }
    function onCancel() { cleanup(false); }

    okBtn.addEventListener('click', onOk);
    cancelBtn.addEventListener('click', onCancel);
    backdrop.addEventListener('click', onCancel);
  });
}

async function serverAction(action, confirmMsg) {
  if (isOperating) return;
  const confirmed = await showConfirm(confirmMsg);
  if (!confirmed) return;

  isOperating = true;
  setButtonsLoading(true);

  try {
    const res = await fetch('/api/server/' + action, { method: 'POST' });
    const data = await res.json();
    if (data.success) {
      showActionMsg('成功: ' + data.message, true);
      showToast('操作が完了しました', false);
      await fetchDashboard();
    } else {
      showActionMsg('失敗: ' + data.message, false);
      showToast('操作に失敗しました', true);
    }
  } catch (err) {
    showActionMsg('失敗: ' + err.message, false);
    showToast('通信エラー', true);
  } finally {
    isOperating = false;
    setButtonsLoading(false);
  }
}

async function copyText(elementId) {
  const el = document.getElementById(elementId);
  if (!el) return;
  const text = el.textContent.trim();
  if (!text || text === '-') return;
  try {
    await navigator.clipboard.writeText(text);
  } catch (e) {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.left = '-9999px';
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
  }
  showToast('コピーしました', false);
}

async function fetchSupportStatus() {
  try {
    const res = await fetch('/api/support', { cache: 'no-store' });
    if (!res.ok) return;
    const data = await res.json();
    const pill = document.getElementById('support-status-pill');
    if (!pill) return;
    const on = !!data.enabled;
    pill.textContent = on ? 'ON' : 'OFF';
    pill.className = 'support-pill-mini ' + (on ? 'on' : 'off');
  } catch (e) { /* ignore */ }
}

function capMode(s) {
  if (!s || s === '-') return '-';
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function applyExternalCard(external) {
  if (!external) return;

  const playit = external.playit_summary || {};
  const pf = external.portforward_summary || {};

  const playitStateEl = document.getElementById('home-playit-state');
  const playitTargetEl = document.getElementById('home-playit-target');
  const pfStateEl = document.getElementById('home-pf-state');
  const pfTargetEl = document.getElementById('home-pf-target');

  if (playitStateEl && playitTargetEl) {
    const playitReady = playit.state === 'ready';
    playitStateEl.textContent = playitReady ? '🟢 有効' : '🔴 無効';
    playitTargetEl.textContent = playit.connection_target || '-';
  }

  if (pfStateEl && pfTargetEl) {
    const pfReady = pf.state === 'ready';
    pfStateEl.textContent = pfReady ? '🟢 開放済み' : '🔴 未開放';
    pfTargetEl.textContent = pf.connection_target || '-';
  }
}

function updateDashboard(data) {
  const system = data.system;
  const server = data.server;
  const lan = data.lan;
  const external = data.external;
  const minecraft = data.minecraft;
  const log = data.log;

  document.getElementById('product-id').textContent = system.product_id || '-';

  const running = server.status === 'running';
  setStatusDot(document.getElementById('header-dot'), running);
  setStatusDot(document.getElementById('server-dot'), running);
  document.getElementById('header-status-text').textContent = server.status_label;
  document.getElementById('server-status').textContent = running ? '🟢 起動中' : '🔴 停止中';

  document.getElementById('lan-hostname').textContent = lan.hostname;
  document.getElementById('lan-ip').textContent = lan.ip;
  document.getElementById('lan-port').textContent = lan.port;

  applyExternalCard(external);

  const playersHome = data.players || {};
  const homePlayersCount = document.getElementById('home-players-count');
  const homePlayersList = document.getElementById('home-players-list');
  if (homePlayersCount && homePlayersList) {
    const count = playersHome.online_count || 0;
    homePlayersCount.textContent = count + '人';
    homePlayersList.innerHTML = '';
    const list = playersHome.players || [];
    if (!list.length) {
      const empty = document.createElement('p');
      empty.className = 'card-label';
      empty.textContent = '接続中のプレイヤーはいません';
      homePlayersList.appendChild(empty);
    } else {
      list.forEach(function (p) {
        const row = document.createElement('div');
        row.className = 'home-player-row';
        row.innerHTML =
          '<span class="home-player-name">' + p.name + '</span>' +
          '<span>' + (p.online ? '🟢' : '⚫') + '</span>';
        homePlayersList.appendChild(row);
      });
    }
  }

  document.getElementById('mc-players').textContent =
    minecraft.players_online + ' / ' + minecraft.players_max;
  document.getElementById('mc-server-name').textContent = minecraft.server_name || '-';

  const mcVersionEl = document.getElementById('mc-version');
  if (mcVersionEl) {
    mcVersionEl.textContent = minecraft.bedrock_version || '-';
  }
  const mcUptimeEl = document.getElementById('mc-uptime');
  if (mcUptimeEl) {
    mcUptimeEl.textContent = minecraft.server_uptime || '-';
  }

  const iconEl = document.getElementById('home-world-icon');
  const nameEl = document.getElementById('home-world-name');
  const metaEl = document.getElementById('home-world-meta');
  const playersEl = document.getElementById('home-world-players');
  if (iconEl && nameEl) {
    const icons = { default: '🏠', creative: '🏗', adventure: '⚔' };
    let icon = minecraft.world_icon;
    if (!icon || icon === 'default') {
      const gm = (minecraft.gamemode || '').toLowerCase();
      icon = icons[gm] || icons.default;
    }
    iconEl.textContent = icon;
    nameEl.textContent = minecraft.world_name || '-';
    metaEl.textContent = capMode(minecraft.difficulty) + ' · ' + capMode(minecraft.gamemode);
    if (minecraft.players && minecraft.players.length > 0) {
      playersEl.textContent = minecraft.players_online + '人プレイ中（' + minecraft.players.join('、') + '）';
    } else {
      playersEl.textContent = minecraft.players_online + '人プレイ中';
    }
  }

  document.getElementById('sys-cpu').textContent = system.cpu;
  document.getElementById('sys-memory').textContent = system.memory;
  document.getElementById('sys-disk').textContent = system.disk;
  document.getElementById('sys-uptime').textContent = system.uptime;
  document.getElementById('sys-os').textContent = system.os;

  const logBox = document.getElementById('log-box');
  logBox.textContent = (log.logs && log.logs.length > 0)
    ? log.logs.join('\n') : 'ログがありません';

  const discordPill = document.getElementById('discord-status-pill');
  if (discordPill && data.discord) {
    discordPill.textContent = data.discord.status || '未設定';
    discordPill.className = 'discord-pill-mini ' + (data.discord.status_class || 'off');
  }
}

async function fetchServerStatusQuick() {
  try {
    const res = await fetch('/api/server', { cache: 'no-store' });
    if (!res.ok) return;
    const server = await res.json();
    setStatusDot(document.getElementById('header-dot'), server.status === 'running');
    setStatusDot(document.getElementById('server-dot'), server.status === 'running');
    document.getElementById('header-status-text').textContent = server.status_label;
    document.getElementById('server-status').textContent =
      server.status === 'running' ? '🟢 起動中' : '🔴 停止中';
  } catch (e) { /* ignore */ }
}

async function fetchDashboard() {
  if (isOperating) return;
  try {
    const res = await fetch('/api/dashboard', { cache: 'no-store' });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    updateDashboard(await res.json());
  } catch (err) {
    document.getElementById('header-status-text').textContent = '接続エラー';
  }
}

function initApp() {
  document.getElementById('btn-start').addEventListener('click', function () {
    serverAction('start', 'Minecraftサーバーを開始しますか？');
  });
  document.getElementById('btn-stop').addEventListener('click', function () {
    serverAction('stop', 'Minecraftサーバーを停止しますか？');
  });
  document.getElementById('btn-restart').addEventListener('click', function () {
    serverAction('restart', 'Minecraftサーバーを再起動しますか？');
  });
  document.getElementById('btn-scroll-log').addEventListener('click', function () {
    document.getElementById('log-section').scrollIntoView({ behavior: 'smooth' });
  });

  document.querySelectorAll('.btn-copy').forEach(function (btn) {
    btn.addEventListener('click', function () {
      copyText(btn.getAttribute('data-copy'));
    });
  });

  fetchServerStatusQuick();
  fetchDashboard();
  setTimeout(fetchSupportStatus, 1500);
  setInterval(fetchDashboard, POLL_INTERVAL);
  setInterval(fetchSupportStatus, POLL_INTERVAL);
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initApp);
} else {
  initApp();
}
