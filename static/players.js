(function () {
  'use strict';

  const POLL_MS = 10000;
  let players = [];
  let busy = false;

  const $ = function (id) { return document.getElementById(id); };

  const PERM_LABELS = {
    operator: 'オペレーター',
    member: 'メンバー',
    visitor: 'ビジター',
  };

  const ACTION_LABELS = {
    permission: '権限変更',
    ban: 'BAN',
    unban: 'BAN解除',
    kick: 'Kick',
    delete: '削除',
  };

  function showSnackbar(msg, warn) {
    const el = $('snackbar');
    el.textContent = msg;
    el.className = warn ? 'snackbar warn' : 'snackbar';
    el.hidden = false;
    clearTimeout(showSnackbar._t);
    showSnackbar._t = setTimeout(function () { el.hidden = true; }, 4000);
  }

  function showRestartHint(msg) {
    $('restart-hint-text').textContent = msg;
    $('restart-hint-sheet').hidden = false;
  }

  function hideRestartHint() {
    $('restart-hint-sheet').hidden = true;
  }

  function showConfirm(text, okLabel) {
    return new Promise(function (resolve) {
      $('confirm-text').textContent = text;
      $('confirm-ok').textContent = okLabel || '変更';
      $('confirm-sheet').hidden = false;

      function cleanup(result) {
        $('confirm-sheet').hidden = true;
        $('confirm-ok').removeEventListener('click', onOk);
        $('confirm-cancel').removeEventListener('click', onCancel);
        $('confirm-backdrop').removeEventListener('click', onCancel);
        resolve(result);
      }

      function onOk() { cleanup(true); }
      function onCancel() { cleanup(false); }

      $('confirm-ok').addEventListener('click', onOk);
      $('confirm-cancel').addEventListener('click', onCancel);
      $('confirm-backdrop').addEventListener('click', onCancel);
    });
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

  function statusLabel(online) {
    return online ? '🟢 オンライン' : '⚫ オフライン';
  }

  function renderPlayerCard(player) {
    const card = document.createElement('article');
    card.className = 'player-card';
    card.dataset.name = player.name;

    const header = document.createElement('div');
    header.className = 'player-card-header';
    header.innerHTML =
      '<h3 class="player-card-name">' + escapeHtml(player.name) + '</h3>' +
      '<span class="player-card-status">' + statusLabel(player.online) + '</span>';

    const meta = document.createElement('p');
    meta.className = 'player-card-meta';
    meta.innerHTML =
      '最終ログイン: ' + escapeHtml(player.last_seen_label || '-') + '<br>' +
      '初回参加: ' + escapeHtml(player.first_seen_label || '-') + '<br>' +
      'UUID: ' + escapeHtml(player.xuid || '-');

    const permTitle = document.createElement('p');
    permTitle.className = 'player-perm-title';
    permTitle.textContent = '権限';

    const permBox = document.createElement('div');
    permBox.className = 'player-perm-options';
    ['operator', 'member', 'visitor'].forEach(function (perm) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'player-perm-option' + (player.permission === perm ? ' active' : '');
      btn.innerHTML =
        '<span class="player-perm-dot">' + (player.permission === perm ? '●' : '○') + '</span>' +
        '<span>' + PERM_LABELS[perm] + '</span>';
      btn.addEventListener('click', function () {
        onPermissionClick(player, perm);
      });
      permBox.appendChild(btn);
    });

    const actions = document.createElement('div');
    actions.className = 'player-actions';
    const actionDefs = [
      { action: 'kick', label: 'Kick', desc: '一時的に退出' },
      { action: 'ban', label: 'BAN', desc: '退出し、今後接続できない。' },
      { action: 'delete', label: '削除', desc: '一覧から削除' },
    ];
    actionDefs.forEach(function (def) {
      const btn = document.createElement('button');
      btn.type = 'button';
      const offlineKick = def.action === 'kick' && !player.online;
      btn.className = 'btn btn-outline player-action-btn' +
        (def.action === 'ban' || def.action === 'kick' || def.action === 'delete' ? ' btn-danger' : '') +
        (offlineKick ? ' btn-disabled' : '');
      btn.disabled = offlineKick;
      btn.innerHTML =
        '<span class="player-action-label">' + escapeHtml(def.label) + '</span>' +
        (def.desc ? '<span class="player-action-desc">' + escapeHtml(def.desc) + '</span>' : '');
      if (!offlineKick) {
        btn.addEventListener('click', function () {
          runAction(player.name, def.action);
        });
      }
      actions.appendChild(btn);
    });

    card.appendChild(header);
    card.appendChild(meta);
    card.appendChild(permTitle);
    card.appendChild(permBox);
    card.appendChild(actions);
    return card;
  }

  function renderBanList(entries) {
    const box = $('banlist-list');
    box.innerHTML = '';
    if (!entries || !entries.length) {
      box.innerHTML = '<p class="player-empty">BANリストは空です</p>';
      return;
    }
    entries.forEach(function (item) {
      const el = document.createElement('div');
      el.className = 'player-ban-item';
      el.innerHTML =
        '<div class="player-ban-header">' +
          '<div>' +
            '<div class="player-ban-name">' + escapeHtml(item.name || '-') + '</div>' +
            '<div class="player-ban-meta">BAN日時: ' + escapeHtml(item.banned_at_label || '-') + '</div>' +
            '<div class="player-ban-meta">UUID: ' + escapeHtml(item.xuid || '-') + '</div>' +
          '</div>' +
          '<button type="button" class="btn btn-outline btn-unban">BAN解除</button>' +
        '</div>';
      el.querySelector('.btn-unban').addEventListener('click', function () {
        runAction(item.name, 'unban');
      });
      box.appendChild(el);
    });
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function renderPlayers(data) {
    players = data.players || [];
    const box = $('player-list');
    box.innerHTML = '';
    if (!players.length) {
      box.innerHTML = '<p class="player-empty">プレイヤーがまだいません</p>';
    } else {
      players.forEach(function (p) {
        box.appendChild(renderPlayerCard(p));
      });
    }
    $('players-summary').textContent =
      'オンライン ' + (data.online_count || 0) + '人 / 登録 ' + (data.total_count || 0) + '人';
  }

  async function loadPlayers() {
    const q = $('player-search').value.trim();
    const sort = $('player-sort').value;
    const data = await api('GET', '/api/players?sort=' + encodeURIComponent(sort) + '&q=' + encodeURIComponent(q));
    renderPlayers(data);
  }

  async function loadBanlist() {
    const data = await api('GET', '/api/players/bans');
    renderBanList(data.entries || []);
  }

  async function refreshAll() {
    if (busy) return;
    try {
      await loadPlayers();
      await loadBanlist();
    } catch (e) {
      showSnackbar(e.message, true);
    }
  }

  function confirmText(name, action, permission) {
    if (action === 'permission') {
      return name + '\n\nを\n\n' + PERM_LABELS[permission] + '\n\nへ変更します。\n\nよろしいですか？';
    }
    if (action === 'delete') {
      return name + '\n\nを削除します。\n\n参加ログが消え、再参加時は新規登録されます。\n\nよろしいですか？';
    }
    if (action === 'kick') {
      return name + '\n\nをKickします。\n\n一時的に退出させます。\n\nよろしいですか？';
    }
    if (action === 'ban') {
      return name + '\n\nをBANします。\n\n退出し、今後接続できなくなります。\n\nよろしいですか？';
    }
    const label = ACTION_LABELS[action] || action;
    return name + '\n\nを\n\n' + label + '\n\nします。\n\nよろしいですか？';
  }

  function confirmOkLabel(action) {
    if (action === 'permission') return '変更';
    if (action === 'delete') return '削除';
    if (action === 'unban') return '解除';
    if (action === 'kick') return 'Kick';
    if (action === 'ban') return 'BAN';
    return '実行';
  }

  async function runAction(name, action, permission) {
    if (busy) return;
    const ok = await showConfirm(confirmText(name, action, permission), confirmOkLabel(action));
    if (!ok) return;
    busy = true;
    try {
      const body = { name: name, action: action };
      if (permission) body.permission = permission;
      const data = await api('POST', '/api/players/action', body);
      showSnackbar(data.message || '完了しました', false);
      if (data.needs_restart) {
        showRestartHint(data.message + '\n\nサーバーの再起動が必要な場合があります。');
      }
      await refreshAll();
    } catch (e) {
      showSnackbar(e.message, true);
    } finally {
      busy = false;
    }
  }

  function onPermissionClick(player, perm) {
    if (player.permission === perm) return;
    runAction(player.name, 'permission', perm);
  }

  $('player-search').addEventListener('input', function () {
    clearTimeout($('player-search')._t);
    $('player-search')._t = setTimeout(loadPlayers, 300);
  });
  $('player-sort').addEventListener('change', loadPlayers);
  $('restart-hint-ok').addEventListener('click', hideRestartHint);
  $('restart-hint-backdrop').addEventListener('click', hideRestartHint);

  refreshAll();
  setInterval(refreshAll, POLL_MS);
})();
