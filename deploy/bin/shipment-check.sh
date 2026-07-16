#!/bin/bash
# 出荷前チェック（CLI版）
# Web UI の「出荷前テスト」と同じ項目を実行します。
set -euo pipefail

WEB_DIR="/opt/appliance/web"
cd "$WEB_DIR"

python3 -m app.health_check_manager "$@"
