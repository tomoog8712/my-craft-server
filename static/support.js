(function () {
  'use strict';

  const POLL_MS = 5000;
  let busy = false;
  let durationMode = 'enable';

  const $ = function (id) { return document.getElementById(id); };

  function showSnackbar(msg, warn) {
    const el = $('snackbar');
    el.textContent = msg;
    el.className = warn ? 'snackbar warn' : 'snackbar';
    el.hidden = false;
    clearTimeout(showSnackbar._t);
    showSnackbar._t = setTimeout(function () { el.hidden = true; }, 4000);
  }

  function showSheet(id) {
    $(id).hidden = false;
    document.body.style.overflow = 'hidden';
  }

  function hideSheet(id) {
    $(id).hidden = true;
    if (!busy) document.body.style.overflow = '';
  }

  function setBusy(state) {
    busy = state;
    document.body.classList.toggle('ui-disabled', state);
  }

  function renderHistory(history) {
    const box = $('history-list');
    if (!history || !history.length) {
      box.innerHTML = '<p class="card-label">履歴はありません</p>';
      return;
    }
    box.innerHTML = history.map(function (item) {
      return (
        '<div class="history-entry">' +
          '<div class="history-date">' + (item.display_at || item.at || '') + '</div>' +
          '<div class="history-msg">' + item.message + '</div>' +
        '</div>'
      );
    }).join('');
  }

  function renderStatus(data) {
    const enabled = !!data.enabled;
    const stateEl = $('support-state');
    stateEl.textContent = data.status_label || (enabled ? 'ON' : 'OFF');
    stateEl.className = 'support-pill ' + (enabled ? 'on' : 'off');

    $('row-remaining').hidden = !enabled;
    $('row-connected').hidden = !enabled;
    $('row-ip').hidden = !enabled || !data.tailscale_ip;

    $('support-remaining').textContent = enabled ? (data.remaining_label || '-') : '-';
    $('support-connected').textContent = enabled ? (data.connected_label || 'なし') : 'なし';
    $('support-ip').textContent = data.tailscale_ip || '-';

    $('btn-enable').hidden = enabled;
    $('btn-disable').hidden = !enabled;
    $('btn-change-time').hidden = !enabled;

    const notice = $('support-notice');
    if (data.notification === 'active') {
      notice.hidden = false;
      notice.className = 'support-notice active';
      $('support-notice-text').textContent = '🟢 サポート有効';
    } else if (data.notification === 'ended') {
      notice.hidden = false;
      notice.className = 'support-notice ended';
      $('support-notice-text').textContent = 'サポート終了';
    } else {
      notice.hidden = true;
    }

    renderHistory(data.history || []);
  }

  async function fetchStatus() {
    const res = await fetch('/api/support', { cache: 'no-store' });
    if (!res.ok) throw new Error('load failed');
    return res.json();
  }

  async function refresh() {
    if (busy) return;
    try {
      renderStatus(await fetchStatus());
    } catch (e) {
      showSnackbar('状態の取得に失敗しました', true);
    }
  }

  async function postJson(url, body) {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {}),
    });
    const data = await res.json();
    if (!res.ok || !data.success) {
      throw new Error(data.message || '操作に失敗しました');
    }
    return data;
  }

  async function enableWithDuration(duration) {
    setBusy(true);
    try {
      const data = await postJson('/api/support/enable', { duration: duration });
      showSnackbar(data.message || '有効にしました');
      await refresh();
    } catch (e) {
      showSnackbar(e.message, true);
    } finally {
      setBusy(false);
    }
  }

  async function disableSupport() {
    setBusy(true);
    try {
      const data = await postJson('/api/support/disable', {});
      showSnackbar(data.message || '無効にしました');
      await refresh();
    } catch (e) {
      showSnackbar(e.message, true);
    } finally {
      setBusy(false);
    }
  }

  async function changeTime(duration) {
    setBusy(true);
    try {
      const data = await postJson('/api/support/time', { duration: duration });
      showSnackbar(data.message || '更新しました');
      await refresh();
    } catch (e) {
      showSnackbar(e.message, true);
    } finally {
      setBusy(false);
    }
  }

  function openDurationSheet(mode) {
    durationMode = mode;
    showSheet('duration-sheet');
  }

  function bindEvents() {
    $('btn-enable').addEventListener('click', function () {
      showSheet('confirm-sheet');
    });

    $('confirm-cancel').addEventListener('click', function () {
      hideSheet('confirm-sheet');
    });
    $('confirm-backdrop').addEventListener('click', function () {
      hideSheet('confirm-sheet');
    });
    $('confirm-ok').addEventListener('click', function () {
      hideSheet('confirm-sheet');
      openDurationSheet('enable');
    });

    $('duration-backdrop').addEventListener('click', function () {
      hideSheet('duration-sheet');
    });

    document.querySelectorAll('#duration-sheet [data-duration]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        const duration = btn.getAttribute('data-duration');
        hideSheet('duration-sheet');
        if (durationMode === 'change') {
          changeTime(duration);
        } else {
          enableWithDuration(duration);
        }
      });
    });

    $('btn-disable').addEventListener('click', disableSupport);
    $('btn-change-time').addEventListener('click', function () {
      openDurationSheet('change');
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    bindEvents();
    refresh();
    setInterval(refresh, POLL_MS);
  });
})();
