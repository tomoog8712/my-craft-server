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




---

## [Unreleased]

### Added

### Changed

### Fixed

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
