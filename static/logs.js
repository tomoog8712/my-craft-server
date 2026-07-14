(function () {
  'use strict';

  const POLL_MS = 10000;

  async function loadLog() {
    const box = document.getElementById('log-box');
    try {
      const res = await fetch('/api/log', { cache: 'no-store' });
      if (!res.ok) throw new Error('load');
      const data = await res.json();
      const logs = data.logs || [];
      box.textContent = logs.length ? logs.join('\n') : 'ログがありません';
    } catch (e) {
      box.textContent = 'ログの読み込みに失敗しました';
    }
  }

  document.getElementById('btn-refresh').addEventListener('click', loadLog);
  loadLog();
  setInterval(loadLog, POLL_MS);
})();
