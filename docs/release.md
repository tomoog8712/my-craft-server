# リリース手順書

My Craft Server Web UI の製品リリース手順です。

## 前提

- `main` ブランチにリリース対象がマージ済み
- `CHANGELOG.md` の `[Unreleased]` に変更内容が記載済み
- `gh` CLI で GitHub 認証済み
- ローカル作業ディレクトリ: `/opt/appliance/web`

## リリース種別の決定

| コマンド | バージョン変化 | 使う場面 |
|---------|---------------|---------|
| `bump-version.sh patch` | 1.0.0 → 1.0.1 | バグ修正 |
| `bump-version.sh minor` | 1.0.0 → 1.1.0 | 機能追加 |
| `bump-version.sh major` | 1.0.0 → 2.0.0 | 破壊的変更 |

詳細: [versioning.md](versioning.md)

## 手順

### Step 1 — 変更履歴の確認

```bash
cd /opt/appliance/web
grep -A 50 '## \[Unreleased\]' CHANGELOG.md
```

空の場合は `changelog-add.sh` で追記するか、リリースを見送ります。

### Step 2 — バージョン確定

```bash
./scripts/bump-version.sh patch   # minor / major に読み替え
```

実行内容:

1. `VERSION` を更新
2. `CHANGELOG.md` の `[Unreleased]` を `[X.Y.Z] - 日付` にリネーム
3. 新しい空の `[Unreleased]` セクションを追加
4. 比較リンクを更新

### Step 3 — コミット & push

```bash
git add VERSION CHANGELOG.md
git commit -m "chore(release): bump version to $(cat VERSION)"
git push origin main
```

### Step 4 — タグ作成 & GitHub Release

```bash
./scripts/release.sh
```

実行内容:

1. `VERSION` から `vX.Y.Z` タグを作成
2. `origin` にタグを push
3. GitHub Actions が Release を自動作成（本文 = CHANGELOG 該当節）

### Step 5 — 確認

```bash
gh release view "v$(cat VERSION)"
```

ブラウザ: https://github.com/tomoog8712/my-craft-server/releases

### Step 6 — 製品への反映（出荷・現場）

アプライアンス本体へデプロイ:

```bash
# 例: main の特定タグをチェックアウトして配置
cd /opt/appliance/web
git fetch --tags
git checkout v1.0.1
sudo systemctl restart mhserver-web
```

出荷記録に **製品 ID**・**ソフトウェア版（タグ）**・**日付** を残してください。

## 緊急修正（ホットフィックス）

```bash
git checkout main
# 修正
./scripts/changelog-add.sh fixed "緊急修正の内容"
./scripts/bump-version.sh patch
git add -A && git commit -m "fix: 緊急修正の要約"
git push origin main
./scripts/release.sh
```

## ロールバック

```bash
cd /opt/appliance/web
git checkout v1.0.0        # 前のタグ
sudo systemctl restart mhserver-web
```

## GitHub Releases 運用

| 項目 | 方針 |
|------|------|
| タグ形式 | `v1.0.0`（`v` + SemVer） |
| タイトル | `My Craft Server Web UI v1.0.0` |
| 本文 | `CHANGELOG.md` から自動抽出 |
| 下書き | 使わない（タグ push で即公開） |
| 資産 | 現時点ではソースタグのみ（ビルド成果物なし） |

### Release ノート例

```markdown
## My Craft Server Web UI v1.0.1

### Fixed
- BAN 解除後の再接続不具合を修正

### Changed
- メンテナンスメニューの文言を整理
```

## トラブルシューティング

| 問題 | 対処 |
|------|------|
| Release が作成されない | Actions タブで workflow ログを確認 |
| タグが既に存在 | `git tag -d vX.Y.Z && git push origin :refs/tags/vX.Y.Z` で削除後やり直し |
| CHANGELOG が空 | `bump-version.sh` 前に `changelog-add.sh` で追記 |

## チェックリスト（リリース前）

- [ ] `[Unreleased]` に変更内容あり
- [ ] 動作確認済み
- [ ] `VERSION` / タグ / CHANGELOG の版が一致
- [ ] `main` に push 済み
- [ ] GitHub Release 作成確認
- [ ] 出荷記録に版数を記載
