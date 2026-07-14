# バージョン管理方針

My Craft Server Web UI のバージョンは **Semantic Versioning 2.0.0** に従います。

```
MAJOR.MINOR.PATCH
  │     │     └── バグ修正（後方互換）
  │     └──────── 機能追加（後方互換）
  └────────────── 破壊的変更
```

## 正（Single Source of Truth）

| ファイル | 役割 |
|---------|------|
| `VERSION` | 現在の製品バージョン（例: `1.0.0`） |
| `CHANGELOG.md` | ユーザー向け変更履歴 |
| Git タグ `vX.Y.Z` | リリース時のスナップショット |

`VERSION` とタグは **常に一致** させます。

## バージョンアップの判断

### PATCH（1.0.0 → 1.0.1）

- バグ修正
- 文言・UI の軽微な修正
- セキュリティ修正（後方互換を保つ場合）

### MINOR（1.0.1 → 1.1.0）

- 新機能追加
- 既存 API・画面の拡張（破壊的変更なし）
- 非推奨化の告知

### MAJOR（1.1.0 → 2.0.0）

- 既存の操作・API が変わる
- 設定形式の破壊的変更
- 大規模な UI 再設計

## 製品 ID との関係

| 識別子 | 例 | 説明 |
|--------|-----|------|
| 製品 ID | `MCS-000001` | ハードウェア単位（`/etc/appliance/serial`） |
| ソフトウェア版 | `1.0.0` | 本リポジトリの `VERSION` |

製品 ID とソフトウェア版は別管理です。出荷時は Git タグと `VERSION` を記録してください。

## コマンド

```bash
./scripts/bump-version.sh patch   # 1.0.0 → 1.0.1
./scripts/bump-version.sh minor   # 1.0.0 → 1.1.0
./scripts/bump-version.sh major   # 1.0.0 → 2.0.0
```

## GitHub Releases

タグ `v1.0.0` を push すると GitHub Actions が Release を自動作成します。
Release 本文には `CHANGELOG.md` の該当セクションが転記されます。
