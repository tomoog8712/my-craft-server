(function () {
  'use strict';

  let busy = false;
  let currentResetId = null;
  let currentPreview = null;

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
    $('loading-overlay').hidden = !state;
  }

  function showSheet(id) {
    $(id).hidden = false;
    document.body.style.overflow = 'hidden';
  }

  function hideSheet(id) {
    $(id).hidden = true;
    document.body.style.overflow = '';
  }

  function renderPreviewHtml(preview) {
    function list(items) {
      return '<ul class="preview-list">' + items.map(function (item) {
        return '<li>✔ ' + item + '</li>';
      }).join('') + '</ul>';
    }
    return (
      '<div class="preview-section-title">削除されるもの</div>' +
      list(preview.removed) +
      '<div class="preview-section-title">保持されるもの</div>' +
      list(preview.kept)
    );
  }

  function renderItems(items) {
    const box = $('reset-list');
    box.innerHTML = items.map(function (item) {
      const btnClass = item.danger ? 'btn btn-danger' : 'btn btn-primary';
      return (
        '<section class="card reset-card" data-id="' + item.id + '">' +
          '<h3>' + item.title + '</h3>' +
          '<p>' + item.description + '</p>' +
          '<button type="button" class="' + btnClass + ' reset-btn" data-id="' + item.id + '">初期化</button>' +
        '</section>'
      );
    }).join('');

    box.querySelectorAll('.reset-btn').forEach(function (btn) {
      btn.addEventListener('click', function () {
        openPreview(btn.getAttribute('data-id'));
      });
    });
  }

  async function loadCatalog() {
    try {
      const res = await fetch('/api/reset/catalog', { cache: 'no-store' });
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const data = await res.json();
      renderItems(data.items || []);
    } catch (err) {
      showSnackbar('読み込みに失敗しました', true);
    }
  }

  async function openPreview(resetId) {
    if (busy) return;
    try {
      const res = await fetch('/api/reset/preview/' + encodeURIComponent(resetId), { cache: 'no-store' });
      const data = await res.json();
      if (!res.ok || !data.success) {
        throw new Error(data.message || 'プレビューの取得に失敗しました');
      }
      currentResetId = resetId;
      currentPreview = data.preview;
      $('preview-title').textContent = currentPreview.title;
      $('preview-body').innerHTML = renderPreviewHtml(currentPreview);
      const nextBtn = $('preview-next');
      nextBtn.className = currentPreview.danger ? 'btn btn-danger' : 'btn btn-primary';
      nextBtn.textContent = '続ける';
      showSheet('preview-sheet');
    } catch (err) {
      showSnackbar(err.message || 'プレビューの取得に失敗しました', true);
    }
  }

  function openAuthSheet() {
    hideSheet('preview-sheet');
    $('auth-code').value = '';
    const runBtn = $('auth-run');
    runBtn.className = currentPreview && currentPreview.danger ? 'btn btn-danger' : 'btn btn-primary';
    showSheet('auth-sheet');
    setTimeout(function () { $('auth-code').focus(); }, 100);
  }

  async function executeReset() {
    if (busy || !currentResetId) return;
    const code = $('auth-code').value.trim();
    if (!code) {
      showSnackbar('初期管理コードを入力してください', true);
      return;
    }
    setBusy(true);
    hideSheet('auth-sheet');
    try {
      const res = await fetch('/api/reset/execute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reset_id: currentResetId, admin_code: code }),
      });
      const data = await res.json();
      if (!res.ok || !data.success) {
        throw new Error(data.message || '初期化に失敗しました');
      }
      $('done-title').textContent = data.message || '初期化が完了しました。';
      $('done-body').hidden = !data.reboot;
      showSheet('done-sheet');
    } catch (err) {
      showSnackbar(err.message || '初期化に失敗しました', true);
    } finally {
      setBusy(false);
    }
  }

  $('preview-cancel').addEventListener('click', function () { hideSheet('preview-sheet'); });
  $('preview-backdrop').addEventListener('click', function () { hideSheet('preview-sheet'); });
  $('preview-next').addEventListener('click', openAuthSheet);

  $('auth-cancel').addEventListener('click', function () { hideSheet('auth-sheet'); });
  $('auth-backdrop').addEventListener('click', function () { hideSheet('auth-sheet'); });
  $('auth-run').addEventListener('click', executeReset);
  $('auth-code').addEventListener('keydown', function (e) {
    if (e.key === 'Enter') executeReset();
  });

  $('done-ok').addEventListener('click', function () {
    hideSheet('done-sheet');
    if (!$('done-body').hidden) {
      window.location.href = '/';
      return;
    }
    loadCatalog();
  });
  $('done-backdrop').addEventListener('click', function () { $('done-ok').click(); });

  loadCatalog();
})();
