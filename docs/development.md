# 開発フロー

## ブランチ戦略

| ブランチ | 用途 |
|---------|------|
| `main` | 安定版。リリースタグの基点 |
| `feature/*` | 機能開発（任意） |
| `fix/*` | バグ修正（任意） |

小規模開発では `main` 直接コミットでも可。販売製品として機能が増えたら PR 運用を推奨します。

## 1. 作業開始

```bash
cd /opt/appliance/web
git pull origin main
```

## 2. 実装

- テンプレート: `/opt/appliance/web/templates/`
- 静的ファイル: `/opt/appliance/web/static/`
- API: `/opt/appliance/web/app/`

反映:

```bash
sudo systemctl restart mhserver-web
```

## 3. 変更履歴を記録

```bash
./scripts/changelog-add.sh added "説明"
# または CHANGELOG.md を直接編集
```

## 4. コミット

```bash
git add .
git commit -m "feat(scope): 変更の要約"
git push origin main
```

### コミットメッセージ例

```
feat(players): allow-list enforcement を追加
fix(bedrock): FIFO デッドロックを修正
docs: リリース手順書を追加
chore(release): bump version to 1.0.1
```

## 5. 動作確認チェックリスト

- [ ] ダッシュボード `/` が表示される
- [ ] 変更した画面が表示・操作できる
- [ ] `sudo systemctl status mhserver-web` が active
- [ ] システム診断で重大エラーがない

## 6. リリース

[release.md](release.md) に従いバージョンタグを作成します。

## ファイル所有者

| ユーザー | 役割 |
|---------|------|
| `ubuntu` | 開発・編集 |
| `mhserver` | Gunicorn 実行 |

```bash
sudo chown -R ubuntu:mhserver /opt/appliance/web
sudo find /opt/appliance/web -type d -exec chmod 2775 {} +
sudo find /opt/appliance/web -type f -exec chmod 664 {} +
```

## 関連ドキュメント

- [changelog-guide.md](changelog-guide.md)
- [versioning.md](versioning.md)
- [release.md](release.md)
