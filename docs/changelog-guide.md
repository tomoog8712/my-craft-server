# 変更履歴の書き方

`CHANGELOG.md` は [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/) 形式です。

## 基本ルール

1. **未リリース分** は常に `## [Unreleased]` に書く
2. **リリース時** に `bump-version.sh` が `[Unreleased]` を `[X.Y.Z]` に移動する
3. ユーザーが読む文章で書く（コミットハッシュだけにしない）

## カテゴリ

| カテゴリ | 用途 |
|---------|------|
| **Added** | 新機能 |
| **Changed** | 既存機能の変更 |
| **Deprecated** | 近いうちに削除予定 |
| **Removed** | 削除した機能 |
| **Fixed** | バグ修正 |
| **Security** | セキュリティ関連 |

## 自動で追記する（推奨）

```bash
cd /opt/appliance/web

./scripts/changelog-add.sh added "ワールド詳細モードをデフォルトに変更"
./scripts/changelog-add.sh fixed "Gunicorn control socket 警告を解消"
./scripts/changelog-add.sh changed "メンテナンスの Minecraft設定 をサーバー名変更に改名"
./scripts/changelog-add.sh security "認証まわりのログ出力を抑制"
```

## 手動で書く場合

`CHANGELOG.md` の `## [Unreleased]` 内、該当カテゴリに `- 説明` を追加します。

```markdown
## [Unreleased]

### Added
- プレイヤー管理に検索フィルタを追加

### Fixed
- BAN 解除後の再接続不具合を修正
```

## コミットメッセージとの併用

[Conventional Commits](https://www.conventionalcommits.org/ja/) を推奨します。

```
feat(players): BANリストに削除済みプレイヤーを表示
fix(worlds): 詳細モード切替ボタンを削除
docs: リリース手順書を追加
chore: bump version to 1.0.1
```

| プレフィックス | CHANGELOG カテゴリ |
|---------------|-------------------|
| `feat` | Added |
| `fix` | Fixed |
| `change` / `refactor` | Changed |
| `remove` | Removed |
| `security` | Security |

## リリース時の流れ

1. `[Unreleased]` に必要な項目が揃っているか確認
2. `./scripts/bump-version.sh patch`（種別は適宜）
3. コミット & push
4. `./scripts/release.sh`

空のカテゴリは `bump-version.sh` が自動で削除します。
