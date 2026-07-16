#!/bin/bash
# 手動クローン量産用: 新しい製品シリアルを設定してDDNS再プロビジョニング
#
# 使い方（クローン後・出荷前に各台で実行）:
#   sudo /opt/appliance/bin/factory-clone.sh MCS-000042
#
# 前提: マスターイメージには cloudflare.token と ZONE_ID が設定済み

set -euo pipefail

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 <SERIAL>" >&2
    echo "  例: $0 MCS-000042" >&2
    exit 1
fi

SERIAL="$1"
if [[ ! "$SERIAL" =~ ^(MCS|JRT)-[0-9]{6}$ ]]; then
    echo "ERROR: Invalid serial format: ${SERIAL} (expected MCS-000001)" >&2
    exit 1
fi

APPLIANCE_DIR="/etc/appliance"
LIB="/opt/appliance/lib/cloudflare.sh"

echo "=== Factory Clone Setup ==="
echo "Serial: ${SERIAL}"

# 1. シリアル書き込み
echo "${SERIAL}" > "${APPLIANCE_DIR}/serial"
chmod 444 "${APPLIANCE_DIR}/serial"
echo "OK: serial → ${SERIAL}"

# 2. 前の台のプロビジョニング情報を削除
rm -f "${APPLIANCE_DIR}/.provisioned"
rm -f "${APPLIANCE_DIR}/config.json"
rm -f "${APPLIANCE_DIR}/uuid"
echo "OK: Cleared provisioning state"

# 3. machine-id を再生成（クローン重複対策）
if command -v systemd-machine-id-setup &>/dev/null; then
    systemd-machine-id-setup
    echo "OK: Regenerated machine-id"
fi

# 4. ホスト名を統一（オプション: 全台同じmy-craft-server）
hostnamectl set-hostname my-craft-server 2>/dev/null || true

# 5. DDNS名を表示
if [[ -f "$LIB" ]]; then
    # shellcheck source=/dev/null
    source "$LIB"
    FQDN=$(get_ddns_fqdn "$SERIAL" 2>/dev/null || echo "mc-$(echo $SERIAL | tr A-Z a-z | sed s/jrt-/jrt/).mycraft.server")
    echo "DDNS: ${FQDN}"
fi

# 6. プロビジョニング実行
if [[ -f /opt/appliance/bin/provision.sh ]]; then
    /opt/appliance/bin/provision.sh
fi

echo ""
echo "=== 完了 ==="
echo "台帳に記録: ${SERIAL}"
/opt/appliance/bin/status.sh 2>/dev/null || true
