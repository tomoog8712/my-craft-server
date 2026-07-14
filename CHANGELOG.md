# Changelog

このプロジェクトは [Semantic Versioning](https://semver.org/lang/ja/) に従います。
バージョン番号は `VERSION` ファイルが唯一の正です。

形式は [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/) に基づきます。

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

[Unreleased]: https://github.com/tomoog8712/my-craft-server/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/tomoog8712/my-craft-server/releases/tag/v1.0.0
