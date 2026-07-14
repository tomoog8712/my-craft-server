(function () {
  'use strict';

  const EVENTS = [
    ['server_start', 'サーバー起動'],
    ['server_stop', 'サーバー停止'],
    ['player_join', 'プレイヤー参加'],
    ['player_leave', 'プレイヤー退出'],
    ['player_death', 'プレイヤー死亡'],
    ['backup_success', 'バックアップ成功'],
    ['backup_fail', 'バックアップ失敗'],
    ['update_start', 'アップデート開始'],
    ['update_complete', 'アップデート完了'],
    ['update_fail', 'アップデート失敗'],
    ['world_switch', 'ワールド切替'],
    ['world_create', 'ワールド作成'],
    ['world_delete', 'ワールド削除'],
    ['system_error', 'システムエラー'],
    ['ssd_warning', 'SSD容量警告'],
    ['memory_warning', 'メモリ不足'],
    ['cpu_high', 'CPU高負荷'],
  ];

  let editing = false;
  let currentMasked = '';

  const $ = function (id) { return document.getElementById(id); };

  function showSnack(msg, warn) {
    const el = $('snackbar');
    el.textContent = msg;
    el.className = warn ? 'discord-snackbar warn' : 'discord-snackbar';
    el.hidden = false;
    clearTimeout(showSnack._t);
    showSnack._t = setTimeout(function () { el.hidden = true; }, 4000);
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

  function renderEvents(events) {
    const grid = $('events-grid');
    grid.innerHTML = EVENTS.map(function (pair) {
      const key = pair[0];
      const label = pair[1];
      const checked = events[key] !== false ? 'checked' : '';
      return '<label class="discord-event-item"><input type="checkbox" data-event="' + key + '" ' + checked + '><span>' + label + '</span></label>';
    }).join('');
  }

  function renderHistory(items) {
    const box = $('history-list');
    if (!items || !items.length) {
      box.innerHTML = '<p class="card-label">履歴はありません</p>';
      return;
    }
    box.innerHTML = items.map(function (item) {
      const cls = item.success ? '' : ' fail';
      const detail = item.detail ? '<div class="discord-history-detail">' + item.detail + '</div>' : '';
      return '<div class="discord-history-item' + cls + '"><div class="discord-history-head"><span>' + item.title + '</span><span>' + item.time + '</span></div>' + detail + '</div>';
    }).join('');
  }

  function setWebhookField(masked) {
    currentMasked = masked || '';
    const input = $('webhook-input');
    input.value = masked || '';
    input.readOnly = true;
    input.placeholder = masked ? '' : '未設定';
    editing = false;
    $('btn-edit-webhook').hidden = false;
    $('btn-save-webhook').hidden = true;
  }

  async function loadStatus() {
    const data = await api('GET', '/api/discord');
    const state = $('discord-state');
    state.textContent = data.status || '未設定';
    state.className = 'discord-status-pill ' + (data.status_class || 'off');
    setWebhookField(data.webhook_masked);
    renderEvents(data.events || {});
    renderHistory(data.history || []);
  }

  function bindEvents() {
    $('btn-edit-webhook').addEventListener('click', function () {
      editing = true;
      const input = $('webhook-input');
      input.readOnly = false;
      input.value = '';
      input.placeholder = 'https://discord.com/api/webhooks/...';
      input.focus();
      $('btn-edit-webhook').hidden = true;
      $('btn-save-webhook').hidden = false;
    });

    $('btn-save-webhook').addEventListener('click', async function () {
      const url = $('webhook-input').value.trim();
      if (!url) {
        showSnack('Webhook URLを入力してください', true);
        return;
      }
      try {
        await api('POST', '/api/discord/save', { webhook_url: url });
        showSnack('保存しました');
        await loadStatus();
      } catch (e) {
        showSnack(e.message, true);
      }
    });

    $('btn-test').addEventListener('click', async function () {
      try {
        await api('POST', '/api/discord/test', {});
        showSnack('テスト通知を送信しました');
        await loadStatus();
      } catch (e) {
        showSnack(e.message, true);
      }
    });

    $('btn-save-events').addEventListener('click', async function () {
      const events = {};
      document.querySelectorAll('[data-event]').forEach(function (el) {
        events[el.getAttribute('data-event')] = el.checked;
      });
      try {
        await api('POST', '/api/discord/settings', { events: events });
        showSnack('通知設定を保存しました');
      } catch (e) {
        showSnack(e.message, true);
      }
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    bindEvents();
    loadStatus().catch(function (e) { showSnack(e.message, true); });
  });
})();
