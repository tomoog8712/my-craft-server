(function () {
  'use strict';

  const ICONS = { default: '🏠', creative: '🏗', pvp: '⚔', adventure: '⚔', survival: '🏠' };
  const RESTART_POLL_MS = 2000;
  const RESTART_POLL_MAX = 90;

  let worlds = [];
  let currentWorld = null;
  let busy = false;

  const $ = function (id) { return document.getElementById(id); };

  function iconFor(w) {
    if (w.icon && w.icon !== 'default') return w.icon;
    if (w.gamemode === 'creative') return ICONS.creative;
    if (w.gamemode === 'adventure') return ICONS.adventure;
    return ICONS.default;
  }

  function cap(s) { return s ? s.charAt(0).toUpperCase() + s.slice(1) : '-'; }

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

  function showView(name) {
    $('view-list').hidden = name !== 'list';
    $('view-create').hidden = name !== 'create';
    $('view-detail').hidden = name !== 'detail';
    $('view-settings').hidden = name !== 'settings';
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

  function renderList() {
    const box = $('world-list');
    box.innerHTML = '';
    worlds.forEach(function (w) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'world-card' + (w.active ? ' active' : '');
      btn.innerHTML =
        '<div class="world-card-head"><span class="world-icon">' + iconFor(w) + '</span>' +
        '<span class="world-title">' + w.display_name +
        (w.folder !== w.display_name ? ' <span class="world-folder">(' + w.folder + ')</span>' : '') +
        '</span></div>' +
        '<div class="world-meta">' + cap(w.gamemode) + ' · ' + cap(w.difficulty) + '<br>' +
        w.size_label + '<br>最終プレイ ' + w.last_played_label + '</div>' +
        '<span class="world-badge' + (w.active ? '' : ' stopped') + '">' +
        (w.active ? '🟢 現在使用中' : '停止中') + '</span>';
      btn.addEventListener('click', function () { openDetail(w.id); });
      box.appendChild(btn);
    });
  }

  function renderDetail(w) {
    $('detail-card').innerHTML =
      '<h2 class="card-title">' + iconFor(w) + ' ' + w.display_name + '</h2>' +
      '<dl class="detail-grid">' +
      row('説明', w.description || '（未設定）') +
      row('ゲームモード', cap(w.gamemode)) +
      row('難易度', cap(w.difficulty)) +
      row('シード', w.seed || '（ランダム）') +
      row('サイズ', w.size_label) +
      row('作成日', (w.created_at || '-').slice(0, 10)) +
      row('最終プレイ', w.last_played_label) +
      row('プレイ人数', w.players_online + ' / ' + w.players_max) +
      (w.players && w.players.length ? row('接続中', w.players.join('、')) : '') +
      row('プレイ時間', w.play_time_label || '-') +
      '</dl>';

    const actions = $('detail-actions');
    actions.innerHTML = '';
    addAction(actions, '▶ 使用する', function () { switchWorld(w); }, !w.active);
    addAction(actions, '⚙ ワールド設定', function () { openSettings(w); });
    addAction(actions, '📄 コピー', function () { copyWorld(w.id); });
    addAction(actions, '💾 バックアップ', function () { createBackup(w.id); });
    addAction(actions, '📤 エクスポート', function () { exportWorld(w.id, w.display_name); });
    addAction(actions, '✏ 名前変更', function () { renameWorld(w); });
    addAction(actions, '📝 説明編集', function () { editDescription(w); });
    addAction(actions, '🖼 アイコン変更', function () { changeIcon(w); });
    addAction(actions, '🗑 削除', function () { deleteWorld(w); }, true, !w.active);

    $('backup-section').hidden = false;
    loadBackups(w.id);
    showView('detail');
  }

  function row(label, val) {
    return '<div class="detail-row"><dt>' + label + '</dt><dd>' + val + '</dd></div>';
  }

  function addAction(box, label, fn, enabled, danger) {
    if (enabled === false) return;
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'action-btn' + (danger ? ' danger' : '');
    b.textContent = label;
    b.addEventListener('click', fn);
    box.appendChild(b);
  }

  function buildSettingsForm() {
    const gamemodes = [
      ['survival', 'Survival'],
      ['creative', 'Creative'],
      ['adventure', 'Adventure'],
    ];
    const difficulties = [
      ['peaceful', 'Peaceful'],
      ['easy', 'Easy'],
      ['normal', 'Normal'],
      ['hard', 'Hard'],
    ];
    const gmBox = $('settings-gamemode');
    const dfBox = $('settings-difficulty');
    if (!gmBox.dataset.ready) {
      gmBox.innerHTML = gamemodes.map(function (pair) {
        return '<label><input type="radio" name="gamemode" value="' + pair[0] + '"> ' + pair[1] + '</label>';
      }).join('');
      dfBox.innerHTML = difficulties.map(function (pair) {
        return '<label><input type="radio" name="difficulty" value="' + pair[0] + '"> ' + pair[1] + '</label>';
      }).join('');
      const basic = [
        ['pvp', 'PvP', true],
        ['show-coordinates', '座標表示', false],
        ['allow-cheats', 'チート許可', false],
        ['force-gamemode', 'ゲームモード強制', false],
      ];
      $('settings-switches-basic').innerHTML = basic.map(function (item) {
        return '<label class="switch-cell"><span>' + item[1] + '</span>' +
          '<input type="checkbox" name="' + item[0] + '"' + (item[2] ? ' checked' : '') + ' class="sw"></label>';
      }).join('');
      const rules = [
        ['spawn_protection', '初期スポーン保護', true],
        ['achievements', '実績', true],
        ['daylight_cycle', '昼夜サイクル', true],
        ['weather', '天候変化', true],
        ['immediate_respawn', '即時リスポーン', false],
        ['mob_spawn', 'Mobスポーン', true],
        ['mob_griefing', 'Mobによる破壊', true],
        ['tnt', 'TNT爆発', true],
        ['fire_spread', '火の延焼', true],
      ];
      $('settings-switches-rules').innerHTML = rules.map(function (item) {
        return '<label class="switch-cell"><span>' + item[1] + '</span>' +
          '<input type="checkbox" name="' + item[0] + '"' + (item[2] ? ' checked' : '') + ' class="sw"></label>';
      }).join('');
      gmBox.dataset.ready = '1';
    }
  }

  function boolOn(val) {
    return String(val).toLowerCase() === 'true';
  }

  function fillSettingsForm(settings) {
    const form = $('settings-form');
    form.querySelector('input[name="max_players"]').value = settings.max_players || '10';
    form.querySelector('input[name="seed"]').value = settings.seed || '';
    const gm = settings.gamemode || 'survival';
    const df = settings.difficulty || 'normal';
    form.querySelectorAll('input[name="gamemode"]').forEach(function (el) {
      el.checked = el.value === gm;
    });
    form.querySelectorAll('input[name="difficulty"]').forEach(function (el) {
      el.checked = el.value === df;
    });
    const props = {
      pvp: settings.pvp,
      'show-coordinates': settings['show-coordinates'],
      'allow-cheats': settings['allow-cheats'],
      'force-gamemode': settings['force-gamemode'],
    };
    Object.keys(props).forEach(function (key) {
      const el = form.querySelector('input[name="' + key + '"]');
      if (el) el.checked = boolOn(props[key]);
    });
    const rules = settings.rules || {};
    form.querySelectorAll('#settings-switches-rules input.sw').forEach(function (el) {
      el.checked = boolOn(rules[el.name]);
    });
  }

  function collectSettingsForm(form) {
    const fd = new FormData(form);
    const data = {
      gamemode: fd.get('gamemode'),
      difficulty: fd.get('difficulty'),
      seed: fd.get('seed'),
      max_players: fd.get('max_players'),
    };
    form.querySelectorAll('#settings-switches-basic input.sw, #settings-switches-rules input.sw').forEach(function (el) {
      data[el.name] = el.checked;
    });
    return data;
  }

  async function openSettings(w) {
    buildSettingsForm();
    setBusy(true, '設定を読み込み中…');
    try {
      const data = await api('GET', '/api/worlds/' + w.id + '/settings');
      currentWorld = w;
      const settings = data.settings || data;
      $('settings-title').textContent = (settings.display_name || w.display_name) + ' の設定';
      $('settings-note').textContent = settings.active
        ? 'このワールド専用の設定です。保存後、サーバー再起動で反映されます。'
        : 'このワールド専用の設定です。他のワールドには影響しません。';
      fillSettingsForm(settings);
      showView('settings');
    } catch (e) {
      showSnackbar(e.message, true);
    } finally {
      setBusy(false);
    }
  }

  async function fetchServerStatus() {
    const res = await fetch('/api/server', { cache: 'no-store' });
    const data = await res.json();
    return data.status;
  }

  async function waitForRunning() {
    for (let i = 0; i < RESTART_POLL_MAX; i++) {
      await new Promise(function (r) { setTimeout(r, RESTART_POLL_MS); });
      try {
        if (await fetchServerStatus() === 'running') return true;
      } catch (e) { /* retry */ }
    }
    return false;
  }

  async function navigateAfterSave(worldId) {
    setBusy(true, '読み込み中…');
    try {
      await loadWorlds();
      const data = await api('GET', '/api/worlds/' + worldId);
      currentWorld = data.world || data;
      renderDetail(currentWorld);
    } catch (e) {
      showSnackbar(e.message, true);
      showView('list');
      try { await loadWorlds(); } catch (err) { /* ignore */ }
    } finally {
      setBusy(false);
    }
  }

  async function saveSettings(e) {
    e.preventDefault();
    if (!currentWorld) return;
    const worldId = currentWorld.id;
    const isActive = !!currentWorld.active;

    if (isActive) {
      const ok = await showConfirm(
        '設定を反映するには\nMinecraftサーバーを再起動します。\n\n保存して再起動しますか？',
        '保存する'
      );
      if (!ok) return;
    }

    setBusy(true, isActive ? '設定を反映しています…（再起動中）' : '保存中…');
    try {
      const payload = collectSettingsForm(e.target);
      const data = await api('POST', '/api/worlds/' + worldId + '/settings', payload);
      showSnackbar(data.message || (data.restarted ? '設定を反映しました' : '保存しました'));
    } catch (err) {
      showSnackbar(err.message, true);
      setBusy(false);
      return;
    }
    await navigateAfterSave(worldId);
  }

  async function loadWorlds() {
    const data = await api('GET', '/api/worlds');
    worlds = data.worlds || [];
    renderList();
  }

  async function openDetail(id) {
    setBusy(true, '読み込み中…');
    try {
      const data = await api('GET', '/api/worlds/' + id);
      currentWorld = data.world || data;
      renderDetail(currentWorld);
    } catch (e) {
      showSnackbar(e.message, true);
    } finally {
      setBusy(false);
    }
  }

  async function switchWorld(w) {
    const ok = await showConfirm(
      '現在のワールドを保存します。\n\nワールドを切り替えるには\nMinecraftサーバーを再起動します。\n\nよろしいですか？',
      '切り替える'
    );
    if (!ok) return;
    setBusy(true, 'ワールドを切り替えています…');
    try {
      await api('POST', '/api/worlds/switch', { id: w.id });
      showSnackbar('ワールドを切り替えました');
      await loadWorlds();
      openDetail(w.id);
    } catch (e) {
      showSnackbar(e.message, true);
    } finally {
      setBusy(false);
    }
  }

  async function copyWorld(id) {
    setBusy(true, 'コピー中…');
    try {
      const data = await api('POST', '/api/worlds/copy', { id: id });
      showSnackbar('ワールドをコピーしました');
      await loadWorlds();
      if (data.world_id) openDetail(data.world_id);
      else showView('list');
    } catch (e) {
      showSnackbar(e.message, true);
    } finally {
      setBusy(false);
    }
  }

  function deleteWorld(w) {
    $('delete-target-name').textContent = '「' + w.display_name + '」';
    $('delete-confirm-input').value = '';
    $('delete-sheet').hidden = false;
    document.body.style.overflow = 'hidden';
    function close() {
      $('delete-sheet').hidden = true;
      document.body.style.overflow = '';
      $('delete-ok').removeEventListener('click', onOk);
      $('delete-cancel').removeEventListener('click', close);
      $('delete-backdrop').removeEventListener('click', close);
    }
    async function onOk() {
      const name = $('delete-confirm-input').value.trim();
      close();
      setBusy(true, '削除中…');
      try {
        await api('POST', '/api/worlds/delete', { id: w.id, confirm_name: name });
        showSnackbar('削除しました');
        currentWorld = null;
        showView('list');
        await loadWorlds();
      } catch (e) {
        showSnackbar(e.message, true);
      } finally {
        setBusy(false);
      }
    }
    $('delete-ok').addEventListener('click', onOk);
    $('delete-cancel').addEventListener('click', close);
    $('delete-backdrop').addEventListener('click', close);
  }

  async function renameWorld(w) {
    const name = prompt('新しいワールド名', w.display_name);
    if (!name || name === w.display_name) return;
    setBusy(true);
    try {
      await api('POST', '/api/worlds/rename', { id: w.id, name: name });
      showSnackbar('名前を変更しました');
      await loadWorlds();
      openDetail(w.id);
    } catch (e) {
      showSnackbar(e.message, true);
    } finally {
      setBusy(false);
    }
  }

  async function editDescription(w) {
    const desc = prompt('説明（自由入力）', w.description || '');
    if (desc === null) return;
    setBusy(true);
    try {
      await api('POST', '/api/worlds/meta', { id: w.id, description: desc });
      showSnackbar('説明を保存しました');
      await loadWorlds();
      openDetail(w.id);
    } catch (e) {
      showSnackbar(e.message, true);
    } finally {
      setBusy(false);
    }
  }

  async function changeIcon(w) {
    const icons = ['🏠', '🏗', '⚔', '🌲', '🏔', '⛏', '🐉', '🌊', '🏰', '🎮'];
    const current = iconFor(w);
    const pick = prompt('アイコンを入力（例: 🏠 🏗 ⚔）\n' + icons.join(' '), current);
    if (!pick) return;
    setBusy(true);
    try {
      await api('POST', '/api/worlds/meta', { id: w.id, icon: pick.trim() });
      showSnackbar('アイコンを変更しました');
      await loadWorlds();
      openDetail(w.id);
    } catch (e) {
      showSnackbar(e.message, true);
    } finally {
      setBusy(false);
    }
  }

  async function parseApiResponse(res) {
    const text = await res.text();
    try {
      return JSON.parse(text);
    } catch (e) {
      if (res.status === 413) {
        throw new Error('ファイルが大きすぎます。しばらくしてから再試行してください');
      }
      if (text.indexOf('<html') !== -1) {
        throw new Error('サーバーでエラーが発生しました（' + res.status + '）');
      }
      throw new Error(text || 'エラーが発生しました');
    }
  }

  async function importFile(file) {
    if (!file) return;
    const lower = (file.name || '').toLowerCase();
    if (!lower.endsWith('.zip') && !lower.endsWith('.mcworld')) {
      showSnackbar('.zip または .mcworld ファイルを選択してください', true);
      return;
    }
    const form = new FormData();
    form.append('file', file);
    setBusy(true, 'インポート中…（大きいワールドは数分かかることがあります）');
    try {
      const res = await fetch('/api/worlds/import', { method: 'POST', body: form });
      const data = await parseApiResponse(res);
      if (!res.ok || !data.success) throw new Error(data.message || '失敗');
      showSnackbar('インポートしました');
      await loadWorlds();
      showView('list');
    } catch (err) {
      showSnackbar(err.message, true);
    } finally {
      setBusy(false);
    }
  }

  function setupDropZone() {
    let dragDepth = 0;
    const overlay = $('drop-overlay');
    document.addEventListener('dragenter', function (e) {
      e.preventDefault();
      dragDepth += 1;
      if (dragDepth === 1) overlay.hidden = false;
    });
    document.addEventListener('dragleave', function (e) {
      e.preventDefault();
      dragDepth -= 1;
      if (dragDepth <= 0) {
        dragDepth = 0;
        overlay.hidden = true;
      }
    });
    document.addEventListener('dragover', function (e) { e.preventDefault(); });
    document.addEventListener('drop', function (e) {
      e.preventDefault();
      dragDepth = 0;
      overlay.hidden = true;
      const file = e.dataTransfer.files && e.dataTransfer.files[0];
      importFile(file);
    });
  }

  async function createBackup(id) {
    setBusy(true, 'バックアップ中…');
    try {
      await api('POST', '/api/worlds/backup', { id: id });
      showSnackbar('バックアップを作成しました');
      loadBackups(id);
    } catch (e) {
      showSnackbar(e.message, true);
    } finally {
      setBusy(false);
    }
  }

  async function loadBackups(id) {
    try {
      const data = await api('GET', '/api/worlds/' + id + '/backups');
      const list = $('backup-list');
      const items = data.backups || [];
      if (!items.length) {
        list.innerHTML = '<p class="card-label">バックアップはありません</p>';
        return;
      }
      list.innerHTML = items.map(function (b) {
        return '<div class="backup-item"><span>' + b.created_label + ' · ' + b.size_label +
          '</span><span class="backup-actions">' +
          '<button type="button" data-restore="' + b.id + '">復元</button>' +
          '<button type="button" data-del="' + b.id + '">削除</button></span></div>';
      }).join('');
      list.querySelectorAll('[data-restore]').forEach(function (btn) {
        btn.addEventListener('click', function () { restoreBackup(id, btn.getAttribute('data-restore')); });
      });
      list.querySelectorAll('[data-del]').forEach(function (btn) {
        btn.addEventListener('click', function () { removeBackup(id, btn.getAttribute('data-del')); });
      });
    } catch (e) {
      $('backup-list').innerHTML = '<p class="card-label">読み込み失敗</p>';
    }
  }

  async function restoreBackup(worldId, backupId) {
    const ok = await showConfirm('このバックアップに復元しますか？', '復元する');
    if (!ok) return;
    setBusy(true, '復元中…');
    try {
      await api('POST', '/api/worlds/restore', { id: worldId, backup_id: backupId });
      showSnackbar('復元しました');
      loadBackups(worldId);
    } catch (e) {
      showSnackbar(e.message, true);
    } finally {
      setBusy(false);
    }
  }

  async function removeBackup(worldId, backupId) {
    try {
      await api('POST', '/api/worlds/backup/delete', { id: worldId, backup_id: backupId });
      loadBackups(worldId);
    } catch (e) {
      showSnackbar(e.message, true);
    }
  }

  async function exportWorld(id, displayName) {
    setBusy(true, 'エクスポート中…');
    try {
      const res = await fetch('/api/worlds/export?id=' + encodeURIComponent(id), { cache: 'no-store' });
      if (!res.ok) {
        const data = await res.json().catch(function () { return {}; });
        throw new Error(data.message || 'エクスポートに失敗しました');
      }
      const blob = await res.blob();
      let filename = (displayName || 'world') + '.mcworld';
      const disp = res.headers.get('Content-Disposition') || '';
      const match = /filename\*=UTF-8''([^;]+)|filename="?([^";]+)"?/i.exec(disp);
      if (match) {
        filename = decodeURIComponent((match[1] || match[2] || filename).replace(/"/g, ''));
      }
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      showSnackbar('エクスポートしました');
    } catch (e) {
      showSnackbar(e.message, true);
    } finally {
      setBusy(false);
    }
  }

  function collectCreateForm(form) {
    const fd = new FormData(form);
    const data = { name: fd.get('name') };
    data.gamemode = fd.get('gamemode');
    data.difficulty = fd.get('difficulty');
    data.seed = fd.get('seed');
    data.max_players = fd.get('max_players');
    form.querySelectorAll('input.sw').forEach(function (el) {
      data[el.name] = el.checked;
    });
    return data;
  }

  function bindEvents() {
    $('btn-import-list').addEventListener('click', function () { $('import-input').click(); });
    $('btn-new-world').addEventListener('click', function () {
      showView('create');
      $('create-form').reset();
    });
    $('btn-create-cancel').addEventListener('click', function () { showView('list'); });
    $('btn-settings-cancel').addEventListener('click', function () {
      if (currentWorld) openDetail(currentWorld.id);
      else showView('list');
    });
    $('settings-form').addEventListener('submit', saveSettings);
    $('create-form').addEventListener('submit', async function (e) {
      e.preventDefault();
      setBusy(true, 'ワールドを作成しています…');
      try {
        const data = await api('POST', '/api/worlds/create', collectCreateForm(e.target));
        showSnackbar('ワールドを作成しました');
        await loadWorlds();
        showView('list');
        if (data.world_id) setTimeout(function () { openDetail(data.world_id); }, 500);
      } catch (err) {
        showSnackbar(err.message, true);
      } finally {
        setBusy(false);
      }
    });
    $('btn-backup-create').addEventListener('click', function () {
      if (currentWorld) createBackup(currentWorld.id);
    });
    $('import-input').addEventListener('change', async function (e) {
      const file = e.target.files[0];
      await importFile(file);
      e.target.value = '';
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    buildSettingsForm();
    bindEvents();
    setupDropZone();
    showView('list');
    loadWorlds().catch(function (e) { showSnackbar(e.message, true); });
  });
})();
