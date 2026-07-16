#!/bin/bash
# Display appliance status (for CLI and future web UI)

set -euo pipefail

APPLIANCE_DIR="/etc/appliance"
CONFIG="${APPLIANCE_DIR}/config.json"
LIB="/opt/appliance/lib/cloudflare.sh"

# shellcheck source=/dev/null
[[ -f "$LIB" ]] && source "$LIB"

get_lan_ip() { hostname -I | awk '{print $1}'; }
get_hostname() { hostname; }
get_mdns() {
    if command -v avahi-resolve &>/dev/null; then
        avahi-resolve -4 -n "$(hostname).local" 2>/dev/null | awk '{print $1}' || echo "$(hostname).local"
    else
        echo "$(hostname).local"
    fi
}

echo "=============================="
echo " My Craft Server Status"
echo "=============================="
echo ""
echo "[LAN]"
echo "  IP:       $(get_lan_ip)"
echo "  Hostname: $(get_hostname)"
echo "  mDNS:     $(get_mdns)"
echo "  Port:     19132"
echo ""
echo "[Minecraft]"
if systemctl is-active --quiet bedrock 2>/dev/null; then
    echo "  Server:   running"
else
    echo "  Server:   stopped"
fi
echo ""
echo "[外部接続]"
serial_file="${APPLIANCE_DIR}/serial"
if [[ -f "$serial_file" ]]; then
    product_id=$(tr -d '[:space:]' < "$serial_file")
else
    product_id="-"
fi
if [[ -f "$CONFIG" ]] && jq empty "$CONFIG" 2>/dev/null; then
    hostname_ddns=$(jq -r '.ddns.hostname // "未設定"' "$CONFIG")
    status=$(jq -r '.ddns.status // "unknown"' "$CONFIG")
    last_ip=$(jq -r '.ddns.last_ip // "未取得"' "$CONFIG")
    last_updated=$(jq -r '.ddns.last_updated // "-"' "$CONFIG")
    cfg_product_id=$(jq -r '.product_id // ""' "$CONFIG")
    if [[ -n "$cfg_product_id" && "$cfg_product_id" != "null" ]]; then
        product_id="$cfg_product_id"
    fi
    ext_port=$(grep -E '^EXTERNAL_PORT=' /etc/appliance/settings.conf 2>/dev/null | cut -d= -f2 || echo "19134")

    live_ip=""
    if command -v curl &>/dev/null; then
        live_ip=$(curl -4 -fsSL --max-time 5 https://api.ipify.org 2>/dev/null || echo "")
    fi

    case "$status" in
        ok) status_ja="接続可能" ;;
        pending_credentials) status_ja="要Cloudflare設定" ;;
        *) status_ja="$status" ;;
    esac

    echo "  製品ID:       ${product_id}"
    echo "  DDNS:         ${hostname_ddns}"
    echo "  状態:         ${status_ja}"
    echo "  登録IP:       ${last_ip}"
    echo "  現在のグローバルIP: ${live_ip:-取得失敗}"
    echo "  最終DDNS更新: ${last_updated}"
    echo "  外部ポート:   ${ext_port}"
else
    echo "  製品ID:       ${product_id}"
    echo "  DDNS:         未設定（未プロビジョニングまたは設定ファイル不正）"
fi
echo ""
echo "=============================="
