/**
 * i18n - Japanese / English (Settings V2)
 */
const I18N = {
  ja: {
    settings_title: '設定',
    settings_subtitle: 'サーバー名',
    back_dashboard: '戻る',
    language: '言語',
    lang_ja: '日本語',
    lang_en: 'English',
    cat_basic: 'サーバー名',
    settings_note: 'Minecraftのサーバー一覧に表示される名前です。ゲームモード・難易度・人数などはワールド管理から変更できます。',
    cat_world: 'ワールド',
    cat_player: 'プレイヤー',
    cat_performance: 'パフォーマンス',
    cat_network: 'ネットワーク',
    cat_log: 'ログ',
    cat_advanced: '詳細設定',
    badge_advanced: '上級者向け',
    cat_allowlist: '参加許可リスト',
    cat_permissions: '管理者設定',
    cat_backup: 'バックアップ',
    cat_discord: 'Discord通知',
    cat_update: 'アップデート',
    coming_soon: '準備中',
    peaceful: 'Peaceful',
    easy: 'Easy',
    normal: 'Normal',
    hard: 'Hard',
    survival: 'サバイバル',
    creative: 'クリエイティブ',
    adventure: 'アドベンチャー',
    changes_title: '変更があります',
    changes_sub: '設定を反映してください',
    apply_changes: '反映する',
    saved_dialog_title: '設定を保存しました。',
    saved_dialog_body: '反映するには\nMinecraftサーバーの再起動が必要です。\n\n今すぐ反映しますか？',
    later: 'あとで',
    restart_now: '今すぐ反映',
    pending_text: '未反映の設定があります',
    apply_now: '今すぐ反映',
    restarting_title: 'Minecraftサーバーを再起動しています…',
    restarting_wait: 'しばらくお待ちください…',
    applied: '設定が反映されました。',
    online_mode_warn_title: 'オンライン認証をOFFにしますか？',
    online_mode_warn: 'セキュリティが低下します。Microsoftアカウントなしで接続できるようになります。',
    confirm_ok: 'OK',
    confirm_cancel: 'キャンセル',
    load_error: '設定の読み込みに失敗しました',
    save_error: '保存に失敗しました',
    restart_fail: '再起動に失敗しました',
    loading_settings: '読み込み中…',
    port_ipv4: 'ポート (IPv4)',
    port_ipv6: 'ポート (IPv6)',
    hint_server_name: 'サーバー一覧に表示される名前です。',
    hint_max_players: '同時に参加できる最大人数です。',
    hint_gamemode: '新しいプレイヤーのゲームモードです。',
    hint_difficulty: 'モンスターの強さなどが変わります。',
    hint_pvp: 'プレイヤー同士で攻撃できます。',
    hint_show_coordinates: '画面に座標を表示します。',
    hint_level_name: 'ワールドの名前です。',
    hint_level_seed: '同じシードなら同じ地形になります。',
    hint_default_player_permission_level: '初参加プレイヤーの権限です。',
    hint_allow_list: '登録したプレイヤーのみ参加できます。',
    hint_online_mode: 'Microsoftアカウントでの認証が必要です。',
    hint_texturepack_required: 'テクスチャパックの使用を必須にします。',
    hint_player_idle_timeout: '放置したプレイヤーを退出させる時間です。',
    hint_view_distance: '遠くまで描画します。大きいほど負荷が増えます。',
    hint_tick_distance: 'ワールドの更新範囲です。大きいほど負荷が増えます。',
    hint_enable_lan_visibility: 'LAN内の他端末からサーバーを探せます。',
    hint_server_port: 'Minecraftが使うポート番号です。',
    hint_server_portv6: 'IPv6用のポート番号です。',
    hint_content_log_level: 'ログの詳しさを設定します。',
    hint_compression_threshold: '通信を圧縮するしきい値です。',
    hint_compression_algorithm: '圧縮の方式です。',
    visitor: 'ビジター',
    member: 'メンバー',
    operator: 'オペレーター',
    zlib: 'zlib',
    snappy: 'snappy',
  },
  en: {
    settings_title: 'Settings',
    settings_subtitle: 'Server Name',
    back_dashboard: 'Back',
    language: 'Language',
    lang_ja: '日本語',
    lang_en: 'English',
    cat_basic: 'Server Name',
    settings_note: 'Name shown in the Minecraft server list. Game mode, difficulty, and player limits are configured per world.',
    cat_world: 'World',
    cat_player: 'Players',
    cat_performance: 'Performance',
    cat_network: 'Network',
    cat_log: 'Logs',
    cat_advanced: 'Advanced',
    badge_advanced: 'Expert',
    cat_allowlist: 'Allowlist',
    cat_permissions: 'Permissions',
    cat_backup: 'Backups',
    cat_discord: 'Discord',
    cat_update: 'Updates',
    coming_soon: 'Coming Soon',
    peaceful: 'Peaceful',
    easy: 'Easy',
    normal: 'Normal',
    hard: 'Hard',
    survival: 'Survival',
    creative: 'Creative',
    adventure: 'Adventure',
    changes_title: 'Unsaved changes',
    changes_sub: 'Apply your settings',
    apply_changes: 'Apply',
    saved_dialog_title: 'Settings saved.',
    saved_dialog_body: 'A server restart is required\nto apply changes.\n\nRestart now?',
    later: 'Later',
    restart_now: 'Restart Now',
    pending_text: 'Restart required',
    apply_now: 'Apply Now',
    restarting_title: 'Restarting server…',
    restarting_wait: 'Please wait…',
    applied: 'Settings applied.',
    online_mode_warn_title: 'Disable online mode?',
    online_mode_warn: 'Security will be reduced.',
    confirm_ok: 'OK',
    confirm_cancel: 'Cancel',
    load_error: 'Failed to load settings',
    save_error: 'Failed to save settings',
    restart_fail: 'Restart failed',
    loading_settings: 'Loading…',
    port_ipv4: 'Port (IPv4)',
    port_ipv6: 'Port (IPv6)',
    hint_server_name: 'Name shown in the server list.',
    hint_max_players: 'Maximum number of players.',
    hint_gamemode: 'Default game mode for new players.',
    hint_difficulty: 'Affects monster strength and more.',
    hint_pvp: 'Players can attack each other.',
    hint_show_coordinates: 'Shows coordinates on screen.',
    hint_level_name: 'Name of the world.',
    hint_level_seed: 'Same seed creates the same terrain.',
    hint_default_player_permission_level: 'Permission for new players.',
    hint_allow_list: 'Only listed players can join.',
    hint_online_mode: 'Requires Microsoft account authentication.',
    hint_texturepack_required: 'Requires texture packs.',
    hint_player_idle_timeout: 'Idle kick timeout in minutes.',
    hint_view_distance: 'Render distance. Higher uses more resources.',
    hint_tick_distance: 'World update range. Higher uses more resources.',
    hint_enable_lan_visibility: 'Makes server discoverable on LAN.',
    hint_server_port: 'Minecraft server port.',
    hint_server_portv6: 'IPv6 port number.',
    hint_content_log_level: 'Log verbosity level.',
    hint_compression_threshold: 'Network compression threshold.',
    hint_compression_algorithm: 'Compression algorithm.',
    visitor: 'Visitor',
    member: 'Member',
    operator: 'Operator',
    zlib: 'zlib',
    snappy: 'snappy',
  },
};

const PENDING_KEY = 'mhserver_settings_pending';

let currentLang = localStorage.getItem('mhserver_lang') || 'ja';

function t(key) {
  return (I18N[currentLang] && I18N[currentLang][key]) || I18N.ja[key] || key;
}

function fieldHint(key) {
  return t('hint_' + key.replace(/-/g, '_'));
}

function setLang(lang) {
  currentLang = lang;
  localStorage.setItem('mhserver_lang', lang);
  document.documentElement.lang = lang === 'ja' ? 'ja' : 'en';
}

function applyI18n() {
  document.querySelectorAll('[data-i18n]').forEach(function (el) {
    const key = el.getAttribute('data-i18n');
    const val = t(key);
    if (key === 'saved_dialog_body') {
      el.innerHTML = val.replace(/\n/g, '<br>');
    } else {
      el.textContent = val;
    }
  });
  const langLabel = document.getElementById('lang-label');
  if (langLabel) langLabel.textContent = currentLang === 'ja' ? t('lang_ja') : t('lang_en');
}

function isPendingRestart() {
  return localStorage.getItem(PENDING_KEY) === '1';
}

function setPendingRestart(pending) {
  if (pending) localStorage.setItem(PENDING_KEY, '1');
  else localStorage.removeItem(PENDING_KEY);
}
