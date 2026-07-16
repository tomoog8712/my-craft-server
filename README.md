# My Craft Server — Web UI

Minecraft Bedrock 専用アプライアンス **My Craft Server** の管理 Web UI です。

| 項目 | 内容 |
|------|------|
| 製品名 | My Craft Server |
| 製品 ID 形式 | `MCS-000001` |
| 現在バージョン | **1.0.1**（`VERSION` 参照） |
| リポジトリ | https://github.com/tomoog8712/my-craft-server （非公開） |

## 機能概要

- ダッシュボード / プレイヤー管理 / ワールド / アドオン
- 外部接続（Playit.gg・ポート開放）/ システム診断
- アップデート（自動バックアップ付き）/ Discord / リモートサポート / リセット

## ディレクトリ構成

```
/opt/appliance/web/
├── app/              # Flask バックエンド
├── static/           # CSS / JavaScript
├── templates/        # Jinja2 HTML
├── scripts/          # 開発・リリース用スクリプト
├── docs/             # 開発ドキュメント
├── VERSION           # 製品バージョン（正）
├── CHANGELOG.md      # 変更履歴
└── README.md         # 本ファイル
```

## 開発環境

| 項目 | 値 |
|------|-----|
| 配置先 | `/opt/appliance/web` |
| サービス | `mhserver-web.service`（Gunicorn, User=mhserver） |
| 再起動 | `sudo systemctl restart mhserver-web` |

### 権限

編集ユーザー `ubuntu`、実行ユーザー `mhserver` で共有します。

```bash
# デプロイ時（root 所有を避ける）
sudo install -o ubuntu -g mhserver -m 664 <file> /opt/appliance/web/...
```

## バージョン管理（概要）

[Semantic Versioning](https://semver.org/lang/ja/) を採用します。

| 種別 | 例 | 用途 |
|------|-----|------|
| **PATCH** | 1.0.0 → 1.0.1 | バグ修正 |
| **MINOR** | 1.0.1 → 1.1.0 | 後方互換の機能追加 |
| **MAJOR** | 1.1.0 → 2.0.0 | 互換性のない変更 |

詳細は [docs/versioning.md](docs/versioning.md) を参照してください。

## 日常の開発フロー

```bash
cd /opt/appliance/web

# 1. 変更を記録（リリース前でも可）
./scripts/changelog-add.sh added "機能の説明"
./scripts/changelog-add.sh fixed "修正内容"

# 2. コミット
git add .
git commit -m "feat(players): BANリスト表示を改善"

# 3. push
git push origin main
```

## リリース

```bash
# バージョン確定 + CHANGELOG 整理
./scripts/bump-version.sh patch   # または minor / major

# タグ作成 + GitHub Release（Actions が自動作成）
./scripts/release.sh
```

手順の詳細は [docs/release.md](docs/release.md) を参照してください。

## ドキュメント

| ドキュメント | 内容 |
|-------------|------|
| [docs/development.md](docs/development.md) | 開発フロー・コミット規約 |
| [docs/changelog-guide.md](docs/changelog-guide.md) | 変更履歴の書き方 |
| [docs/versioning.md](docs/versioning.md) | バージョン番号の付け方 |
| [docs/release.md](docs/release.md) | リリース手順書 |

## ライセンス

販売製品のため、ライセンスは社内規定に従います。
