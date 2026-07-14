(function () {
  'use strict';

  let busy = false;
  const $ = function (id) { return document.getElementById(id); };

  function setBusy(state, text) {
    busy = state;
    document.body.classList.toggle('ui-disabled', state);
    $('loading-overlay').hidden = !state;
    if (text) $('loading-text').textContent = text;
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

  function renderBackups(backups) {
    const box = $('backup-list');
    if (!backups.length) {
      box.innerHTML = '<p class="card-label">バックアップはありません</p>';
      return;
    }
    box.innerHTML = backups.map(function (item) {
      return (
        '<div class="backup-item" data-id="' + item.id + '">' +
          '<div class="backup-meta">' +
            '<div class="backup-title">' + (item.created_label || item.id) + '</div>' +
            '<div class="backup-sub">Minecraft ' + (item.version || '-') + ' / ' + (item.size_label || '-') + '</div>' +
          '</div>' +
          '<div class="backup-actions">' +
            '<button type="button" class="btn btn-primary btn-restore" data-id="' + item.id + '">復元</button>' +
            '<a class="btn btn-outline" href="/api/backups/' + item.id + '/download" style="text-align:center;text-decoration:none;line-height:2;">ダウンロード</a>' +
            '<button type="button" class="btn btn-stop btn-delete" data-id="' + item.id + '">削除</button>' +
          '</div>' +
        '</div>'
      );
    }).join('');

    box.querySelectorAll('.btn-restore').forEach(function (btn) {
      btn.addEventListener('click', function () {
        const id = btn.getAttribute('data-id');
        showConfirm(
          'バックアップ「' + id + '」から復元します。\n\nサーバーが再起動されます。続行しますか？',
          function () { restoreBackup(id); }
        );
      });
    });

    box.querySelectorAll('.btn-delete').forEach(function (btn) {
      btn.addEventListener('click', function () {
        const id = btn.getAttribute('data-id');
        showConfirm('バックアップ「' + id + '」を削除しますか？', function () { deleteBackup(id); });
      });
    });
  }

  async function loadBackups() {
    const res = await fetch('/api/backups');
    const data = await res.json();
    renderBackups(data.backups || []);
  }

  async function restoreBackup(id) {
    setBusy(true, 'バックアップから復元しています…');
    try {
      const res = await fetch('/api/backups/' + id + '/restore', { method: 'POST' });
      const data = await res.json();
      if (!res.ok || !data.success) throw new Error(data.message || 'restore failed');
      alert('復元が完了しました。');
      loadBackups();
    } catch (e) {
      alert('復元に失敗しました: ' + e.message);
    } finally {
      setBusy(false);
    }
  }

  async function deleteBackup(id) {
    setBusy(true, '削除しています…');
    try {
      const res = await fetch('/api/backups/' + id, { method: 'DELETE' });
      const data = await res.json();
      if (!res.ok || !data.success) throw new Error(data.message || 'delete failed');
      loadBackups();
    } catch (e) {
      alert('削除に失敗しました: ' + e.message);
    } finally {
      setBusy(false);
    }
  }

  document.addEventListener('DOMContentLoaded', loadBackups);
})();
