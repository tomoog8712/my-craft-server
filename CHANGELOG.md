# Changelog

このプロジェクトは [Semantic Versioning](https://semver.org/lang/ja/) に従います。
バージョン番号は `VERSION` ファイルが唯一の正です。

形式は [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/) に基づきます。

## [1.0.1] - 2026-07-16

### Added

- 出荷設定フロー（OSバージョン15回タップ → パスワード認証 → 初期化 → シリアル手入力 → 出荷前チェック）
- 出荷前チェック拡張（製品ID・GRUB・サポートOFF・クローン初期化・Discord/Playit未設定・サービス起動など17項目）
- 出荷前チェック CLI（`deploy/bin/shipment-check.sh`）
- マスター初期セットアップスクリプト（`deploy/bin/install.sh`）
- シリアル設定スクリプト（`deploy/bin/shipment-apply-serial.sh`）
- 工場出荷時リセット向け sanitize スクリプト（`deploy/bin/reset-factory-sanitize.sh`）

### Changed

- 工場出荷時リセットをクローン出荷向けに強化（リモートサポート停止・個体情報キャッシュ削除）
- 出荷前テストの判定を厳格化（警告も出荷不可扱い）
- 外部接続画面の Playit 表示安定化

---

## [1.0.2] - 2026-07-16

### Changed

- 初期セットアップ（`install.sh`）のデフォルトホスト名を `my-craft-server` に変更（`my-craft-server-master` は別環境で使用中のため）

---

## [1.0.3] - 2026-07-19

### Added

- Playit トンネル作成失敗時の日本語エラー表示（`tunnel_hint`）
- 「トンネルを自動作成」後の playit.gg 手動設定案内

### Fixed

- Playit 認証完了後に画面が更新されない問題（claim exchange 早期 return、secret 保存先）
- `ProtectSystem=full` 下で `/etc/playit` への書き込みが失敗する問題（secret を data ディレクトリに統一）
- 認証済みなのに `authenticating` のまま進まない状態遷移
- トンネル作成 API がアドレス未取得でも success を返す問題

### Changed

- 出荷/工場リセットの sanitize で Cloudflare API トークンを保持（内部インフラデータ）
- `install.sh` に Playit systemd drop-in と sudoers（create-tunnel / read-claim-secret）を追加
- `playit-claim-exchange.sh` 認証済み時の secret 回収と stale PID 処理を改善

---

## [Unreleased]

### Added

### Changed

- 初期セットアップ（`install.sh`）で `allow-list=false` を設定（空の allowlist による接続拒否を防止）

### Fixed

- 出荷設定・リセット時の `server.properties` 初期化で `shutil.copyfile` を使用（`copy2` の chmod 失敗を回避）
- 出荷設定のシリアル入力画面で「続行」ボタンが押せない問題を修正（`ui-disabled` の解除タイミング）
- 出荷設定のシリアル更新失敗を修正（`priv-exec.sh` 経由で sandbox 外から `/etc/appliance` を更新）
- 出荷前チェックの Playit 判定を修正（`NONE` 応答を未設定として扱う）
- 出荷設定のアドオン初期化を未設定時スキップ（Bedrock 再起動・起動確認を省略）

### Removed

---

## [1.0.0] - 2026-07-14

### Added

- My Craft Server 管理 Web UI（Flask / Gunicorn）
- ダッシュボード（サーバー状態・LAN/外部接続・プレイヤー・ワールド概要・システム情報）
- プレイヤー管理（Kick / BAN / 権限 / 削除 / BANリスト）
- ワールド管理（作成・切替・インポート/エクスポート・バックアップ・詳細設定）
- アドオン管理（`.mcpack` / `.mcaddon` / `.zip`）
- 外部接続（Playit.gg / ポート開放）
- システム診断・出荷前テスト
- アップデート（更新前の自動バックアップ・失敗時の自動復元）
- Discord 通知・リモートサポート
- リセットセンター
- ログ閲覧（メンテナンスメニュー）
- 開発フローとバージョン管理（CHANGELOG / docs / リリーススクリプト）

### Changed

- 上部ナビを4項目に整理（ダッシュボード / 外部接続 / プレイヤー / ワールド）
- メンテナンス機能をダッシュボードのモーダルに集約
- ワールド管理を詳細モード常時表示に変更

### Removed

- ダッシュボードの製品情報カード
- 未使用ページ（サーバー名変更 `/settings`、システムバックアップ一覧 `/backups`）
- 重複・未使用 API（ワールド別アドオン API 等）

[Unreleased]: https://github.com/tomoog8712/my-craft-server/compare/v1.0.2...HEAD
[1.0.2]: https://github.com/tomoog8712/my-craft-server/releases/tag/v1.0.2
