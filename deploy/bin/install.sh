#!/usr/bin/env bash
# My Craft Server — マスターイメージ初期セットアップ
#
# クローンSSDが作れない場合に、1台ずつこのスクリプトで初期状態へ戻します。
#
# 使い方:
#   sudo /opt/appliance/bin/install.sh
#   sudo /opt/appliance/bin/install.sh --serial MCS-000001
#
# 前提:
#   /opt/appliance/web が配置済みであること（deploy/bin から bin を自動同期）
#   /opt/minecraft-bedrock に Bedrock サーバー本体があること
#
set -euo pipefail

APPLIANCE_ROOT="/opt/appliance"
BIN_DIR="${APPLIANCE_ROOT}/bin"
WEB_DIR="${APPLIANCE_ROOT}/web"
DATA_DIR="${APPLIANCE_ROOT}/data"
ETC_DIR="/etc/appliance"
MINECRAFT_DIR="/opt/minecraft"
BEDROCK_TEMPLATE="/opt/minecraft-bedrock"
HOSTNAME="my-craft-server-master"
MASTER_SERIAL="MCS-000001"
SKIP_BEDROCK=0
SKIP_REBOOT=0

log() { printf '\n==> %s\n' "$*"; }
die() { echo "ERROR: $*" >&2; exit 1; }

usage() {
    sed -n '2,12p' "$0"
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --serial)
            [[ $# -ge 2 ]] || die "--serial には値が必要です"
            MASTER_SERIAL="$2"
            shift 2
            ;;
        --skip-bedrock)
            SKIP_BEDROCK=1
            shift
            ;;
        --skip-reboot)
            SKIP_REBOOT=1
            shift
            ;;
        -h|--help)
            usage
            ;;
        *)
            die "不明な引数: $1"
            ;;
    esac
done

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
    die "root 権限が必要です: sudo bash $0"
fi

if [[ ! "$MASTER_SERIAL" =~ ^(MCS|JRT)-[0-9]{6}$ ]]; then
    die "シリアル形式が不正です: ${MASTER_SERIAL} (例: MCS-000001)"
fi

[[ -d "$WEB_DIR/app" ]] || die "${WEB_DIR}/app がありません。Web UI を先に配置してください。"

DEPLOY_BIN="${WEB_DIR}/deploy/bin"
DEPLOY_LIB="${WEB_DIR}/deploy/lib"
install -d -m 0755 "$BIN_DIR"
install -d -m 0755 "${APPLIANCE_ROOT}/lib"

if [[ -d "$DEPLOY_BIN" ]]; then
    log "deploy/bin から ${BIN_DIR} へスクリプトを同期"
    for script in "${DEPLOY_BIN}"/*.sh "${DEPLOY_BIN}"/mhserver-bedrock; do
        [[ -f "$script" ]] || continue
        install -m 755 "$script" "${BIN_DIR}/$(basename "$script")"
    done
fi

if [[ -d "$DEPLOY_LIB" ]]; then
    for lib in "${DEPLOY_LIB}"/*.sh; do
        [[ -f "$lib" ]] || continue
        install -m 755 "$lib" "${APPLIANCE_ROOT}/lib/$(basename "$lib")"
    done
fi

[[ -x "${BIN_DIR}/bedrock-start.sh" ]] || die "bedrock-start.sh が見つかりません。${DEPLOY_BIN} を確認してください。"

log "My Craft Server 初期セットアップを開始します (serial=${MASTER_SERIAL})"

log "1/12 パッケージをインストール"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
    nginx \
    python3 \
    python3-flask \
    python3-gunicorn \
    avahi-daemon \
    avahi-utils \
    jq \
    curl \
    rsync \
    uuid-runtime \
    netplan.io

log "2/12 ユーザー・グループを作成"
for group in mhserver minecraft playit appliance; do
    getent group "$group" >/dev/null || groupadd -r "$group"
done
getent passwd mhserver >/dev/null || \
    useradd -r -g mhserver -G minecraft,appliance,systemd-journal -d /nonexistent -s /usr/sbin/nologin mhserver
getent passwd minecraft >/dev/null || \
    useradd -r -g minecraft -d /opt/minecraft -s /usr/sbin/nologin minecraft
getent passwd playit >/dev/null || \
    useradd -r -g playit -d /nonexistent -s /usr/sbin/nologin playit
usermod -aG minecraft,appliance,systemd-journal mhserver 2>/dev/null || true

log "3/12 ディレクトリを作成"
install -d -m 0755 "$APPLIANCE_ROOT"/{bin,lib,backups,work}
install -d -m 0775 -o mhserver -g mhserver "$DATA_DIR"
install -d -m 0775 -o mhserver -g mhserver "$DATA_DIR"/{players,worlds,addons}
install -d -m 0775 -o mhserver -g minecraft "$APPLIANCE_ROOT/backups"
install -d -m 0750 -o root -g appliance "$ETC_DIR"
install -d -m 0755 "$MINECRAFT_DIR"
install -d -m 0755 /opt/playit
install -d -m 0755 /var/log/nginx

log "4/12 systemd ユニットを配置"
cat > /etc/systemd/system/bedrock.service <<'EOF'
[Unit]
Description=Minecraft Bedrock Dedicated Server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=minecraft
Group=minecraft
WorkingDirectory=/opt/minecraft
Environment=LD_LIBRARY_PATH=.
ExecStart=/opt/appliance/bin/bedrock-start.sh
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/mhserver-web.service <<'EOF'
[Unit]
Description=My Craft Server Web UI (Gunicorn)
After=network.target

[Service]
Type=simple
User=mhserver
Group=mhserver
WorkingDirectory=/opt/appliance/web
ExecStart=/usr/bin/python3 -m gunicorn --workers 1 --bind 127.0.0.1:5000 --timeout 120 --no-control-socket app.app:app
Restart=on-failure
RestartSec=5
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/opt/appliance/web /opt/appliance/backups /opt/appliance/data /opt/appliance/work /opt/minecraft
ReadOnlyPaths=/etc/appliance /proc /sys

[Install]
WantedBy=multi-user.target
EOF

if [[ -x "${BIN_DIR}/provision.sh" ]]; then
    cat > /etc/systemd/system/appliance-provision.service <<'EOF'
[Unit]
Description=My Craft Server - First Boot DDNS Provisioning
After=network-online.target
Wants=network-online.target
ConditionPathExists=!/etc/appliance/.provisioned

[Service]
Type=oneshot
ExecStart=/opt/appliance/bin/provision.sh
RemainAfterExit=yes
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
fi

log "5/12 nginx を設定"
cat > /etc/nginx/sites-available/mhserver <<'EOF'
server {
    listen 80 default_server;
    listen [::]:80 default_server;

    server_name my-craft-server-master.local my-craft-server-master _;

    client_max_body_size 1024m;

    access_log /var/log/nginx/mhserver.access.log;
    error_log  /var/log/nginx/mhserver.error.log;

    location /api/worlds/import {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 600s;
        proxy_send_timeout 600s;
        client_max_body_size 1024m;
    }

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }

    location /static/ {
        alias /opt/appliance/web/static/;
        expires 1h;
    }
}
EOF
ln -sf /etc/nginx/sites-available/mhserver /etc/nginx/sites-enabled/mhserver
rm -f /etc/nginx/sites-enabled/default
nginx -t

log "6/12 sudoers を設定"
cat > /etc/sudoers.d/mhserver-bedrock <<'EOF'
# My Craft Server - mhserver user bedrock control only
Cmnd_Alias BEDROCKCTL = /usr/bin/systemctl start bedrock, /usr/bin/systemctl stop bedrock, /usr/bin/systemctl restart bedrock, /usr/bin/systemctl is-active bedrock
Cmnd_Alias BEDROCKPLAYER = /opt/appliance/bin/bedrock-console-send.sh, /opt/appliance/bin/bedrock-json-write.sh
Cmnd_Alias SUPPORTCTL = /opt/appliance/bin/support-enable.sh, /opt/appliance/bin/support-disable.sh, /opt/appliance/bin/support-status.sh
Cmnd_Alias PLAYITCTL = /opt/appliance/bin/playit-install.sh, /opt/appliance/bin/playit-enable.sh, /opt/appliance/bin/playit-disable.sh, /opt/appliance/bin/playit-disconnect.sh, /opt/appliance/bin/playit-status.sh, /opt/appliance/bin/playit-save-secret.sh, /opt/appliance/bin/playit-start-agent.sh, /opt/appliance/bin/playit-claim-exchange.sh, /usr/bin/systemctl start playit, /usr/bin/systemctl stop playit, /usr/bin/systemctl restart playit, /usr/bin/systemctl enable playit, /usr/bin/systemctl disable playit
Cmnd_Alias RESETCTL = /opt/appliance/bin/reset-reboot.sh, /opt/appliance/bin/reset-factory-sanitize.sh
Cmnd_Alias SHIPMENTCTL = /opt/appliance/bin/shipment-apply-serial.sh
mhserver ALL=(root) NOPASSWD: BEDROCKCTL, BEDROCKPLAYER, SUPPORTCTL, PLAYITCTL, RESETCTL, SHIPMENTCTL
EOF
chmod 440 /etc/sudoers.d/mhserver-bedrock
visudo -c -f /etc/sudoers.d/mhserver-bedrock

log "7/12 /etc/appliance を初期化"
cat > "${ETC_DIR}/settings.conf" <<'EOF'
# My Craft Server - DDNS Settings
# 工場出荷前または初回セットアップ時に編集してください

DOMAIN_BASE=my-craft-server.com
CLOUDFLARE_ZONE_ID=
CLOUDFLARE_API_TOKEN_FILE=/etc/appliance/cloudflare.token
DDNS_PREFIX=mc
EXTERNAL_PORT=19132
RESET_ADMIN_CODE=1111
EOF
chmod 640 "${ETC_DIR}/settings.conf"
chown root:appliance "${ETC_DIR}/settings.conf"

: > "${ETC_DIR}/cloudflare.token"
chmod 600 "${ETC_DIR}/cloudflare.token"
chown root:root "${ETC_DIR}/cloudflare.token"

echo "${MASTER_SERIAL}" > "${ETC_DIR}/serial"
chmod 444 "${ETC_DIR}/serial"
chown root:root "${ETC_DIR}/serial"

rm -f "${ETC_DIR}/.provisioned" "${ETC_DIR}/config.json" "${ETC_DIR}/uuid"
rm -rf /etc/cloudflared
rm -f /etc/systemd/system/cloudflared.service /etc/systemd/system/multi-user.target.wants/cloudflared.service

log "8/12 管理データを初期化"
systemctl stop bedrock 2>/dev/null || true
if [[ -x "${BIN_DIR}/support-disable.sh" ]]; then
    "${BIN_DIR}/support-disable.sh" 2>/dev/null || true
fi
if [[ -x "${BIN_DIR}/playit-disconnect.sh" ]]; then
    sudo -u mhserver "${BIN_DIR}/playit-disconnect.sh" 2>/dev/null || "${BIN_DIR}/playit-disconnect.sh" 2>/dev/null || true
fi

rm -rf "${DATA_DIR:?}/"*
install -d -m 0775 -o mhserver -g mhserver "${DATA_DIR}"/{players,worlds,addons}

cat > "${DATA_DIR}/external_connection.json" <<'EOF'
{
  "mode": "playit"
}
EOF

cat > "${DATA_DIR}/discord.json" <<'EOF'
{
  "webhook_url": "",
  "events": {
    "server_start": true,
    "server_stop": true,
    "player_join": true,
    "player_leave": true,
    "player_death": true,
    "backup_success": true,
    "backup_fail": true,
    "update_start": true,
    "update_complete": true,
    "update_fail": true,
    "world_switch": true,
    "world_create": true,
    "world_delete": true,
    "system_error": true,
    "ssd_warning": true,
    "memory_warning": true,
    "cpu_high": true
  }
}
EOF

cat > "${DATA_DIR}/discord_history.json" <<'EOF'
{"items": []}
EOF

cat > "${DATA_DIR}/discord_monitor.json" <<'EOF'
{
  "last_poll_at": "",
  "connected_players": [],
  "alerts": {}
}
EOF

cat > "${DATA_DIR}/playit.json" <<'EOF'
{
  "enabled": false,
  "installed": false,
  "authenticated": false,
  "status": "disconnected",
  "claim_code": "",
  "claim_url": "",
  "address": "",
  "host": "",
  "port": 19132,
  "endpoint": "",
  "last_error": "",
  "last_test_ok": null,
  "last_test_message": "",
  "updated_at": ""
}
EOF

cat > "${DATA_DIR}/support_status.json" <<'EOF'
{
  "enabled": false,
  "enabled_at": "",
  "expires_at": "",
  "duration": "",
  "tailscale_ip": "",
  "connected": false,
  "notification": "idle"
}
EOF

cat > "${DATA_DIR}/support_history.json" <<'EOF'
{"entries": []}
EOF

cat > "${DATA_DIR}/players/registry.json" <<'EOF'
{"players": {}}
EOF

cat > "${DATA_DIR}/players/banlist.json" <<'EOF'
{"bans": []}
EOF

cat > "${DATA_DIR}/players/deleted.json" <<'EOF'
{"deleted": []}
EOF

cat > "${DATA_DIR}/players/config.json" <<'EOF'
{
  "death_notify": false
}
EOF

cat > "${DATA_DIR}/worlds/registry.json" <<'EOF'
{
  "active_id": "",
  "worlds": {}
}
EOF

cat > "${DATA_DIR}/worlds/playtime.json" <<'EOF'
{}
EOF

cat > "${DATA_DIR}/addons/registry.json" <<'EOF'
{
  "addons": {},
  "history": []
}
EOF

cat > "${DATA_DIR}/bedrock_version.json" <<'EOF'
{
  "version": "unknown",
  "updated_at": ""
}
EOF

chown -R mhserver:mhserver "${DATA_DIR}"
find "${DATA_DIR}" -type d -exec chmod 775 {} \;
find "${DATA_DIR}" -type f -exec chmod 664 {} \;

log "9/12 Minecraft サーバーを初期化"
if [[ "$SKIP_BEDROCK" -eq 0 ]]; then
    [[ -x "${BEDROCK_TEMPLATE}/bedrock_server" ]] || die "${BEDROCK_TEMPLATE}/bedrock_server がありません"
    systemctl stop bedrock 2>/dev/null || true

    for world_dir in "${MINECRAFT_DIR}"/*/; do
        [[ -d "$world_dir" ]] || continue
        base="$(basename "$world_dir")"
        case "$base" in
            behavior_packs|resource_packs|definitions|config|data|development_*)
                continue
                ;;
        esac
        if [[ -f "${world_dir}/level.dat" ]] || [[ "$base" == *" "* ]] || [[ "$base" == *"level"* ]]; then
            rm -rf "$world_dir"
        fi
    done

    rsync -a --delete \
        --exclude='worlds/' \
        --exclude='Bedrock level/' \
        --exclude='console.fifo' \
        "${BEDROCK_TEMPLATE}/" "${MINECRAFT_DIR}/"

    if [[ -f "${MINECRAFT_DIR}/server.properties" ]]; then
        sed -i 's/^server-name=.*/server-name=my-craft-server/' "${MINECRAFT_DIR}/server.properties"
        sed -i 's/^level-name=.*/level-name=Bedrock level/' "${MINECRAFT_DIR}/server.properties"
        sed -i 's/^server-port=.*/server-port=19132/' "${MINECRAFT_DIR}/server.properties"
    fi

    echo '[]' > "${MINECRAFT_DIR}/allowlist.json"
    echo '[]' > "${MINECRAFT_DIR}/permissions.json"
    rm -f "${MINECRAFT_DIR}/console.fifo"
    rm -rf "${APPLIANCE_ROOT}/backups/"*
    rm -rf "${DATA_DIR}/worlds/"*
    install -d -m 0775 -o mhserver -g mhserver "${DATA_DIR}/worlds"
    echo '{"active_id": "", "worlds": {}}' > "${DATA_DIR}/worlds/registry.json"
    echo '{}' > "${DATA_DIR}/worlds/playtime.json"

    chown -R minecraft:minecraft "${MINECRAFT_DIR}"
    chmod +x "${MINECRAFT_DIR}/bedrock_server"
fi

log "10/12 ブート設定 (GRUB / mDNS / ホスト名)"
NETPLAN="/etc/netplan/00-installer-config.yaml"
IFACE="$(ip -o link show | awk -F': ' '$2 != "lo" && $2 !~ /^(tailscale|docker|br-|veth)/ {print $2; exit}')"
: "${IFACE:=eno1}"
cat > "$NETPLAN" <<EOF
network:
  version: 2
  renderer: networkd
  ethernets:
    ${IFACE}:
      dhcp4: true
      optional: true
EOF
chmod 600 "$NETPLAN"
netplan generate
netplan apply

export DEBIAN_FRONTEND=noninteractive
apt-get install -y -qq avahi-daemon avahi-utils
AVAHI="/etc/avahi/avahi-daemon.conf"
if grep -q '^host-name=' "$AVAHI"; then
    sed -i "s/^host-name=.*/host-name=${HOSTNAME}/" "$AVAHI"
else
    sed -i "/^\[server\]/a host-name=${HOSTNAME}" "$AVAHI"
fi
systemctl enable avahi-daemon
systemctl restart avahi-daemon

GRUB="/etc/default/grub"
if grep -q '^GRUB_TIMEOUT=' "$GRUB"; then
    sed -i 's/^GRUB_TIMEOUT=.*/GRUB_TIMEOUT=0/' "$GRUB"
else
    echo 'GRUB_TIMEOUT=0' >> "$GRUB"
fi
if grep -q '^GRUB_TIMEOUT_STYLE=' "$GRUB"; then
    sed -i 's/^GRUB_TIMEOUT_STYLE=.*/GRUB_TIMEOUT_STYLE=hidden/' "$GRUB"
else
    echo 'GRUB_TIMEOUT_STYLE=hidden' >> "$GRUB"
fi
update-grub

hostnamectl set-hostname "$HOSTNAME"
if grep -q '^127.0.1.1' /etc/hosts; then
    sed -i "s/^127.0.1.1.*/127.0.1.1 ${HOSTNAME}/" /etc/hosts
else
    echo "127.0.1.1 ${HOSTNAME}" >> /etc/hosts
fi

if command -v systemd-machine-id-setup &>/dev/null; then
    systemd-machine-id-setup
fi

log "11/12 権限を調整"
chmod +x "${BIN_DIR}/"*.sh 2>/dev/null || true
chown -R mhserver:mhserver "${WEB_DIR}/static" "${WEB_DIR}/templates" 2>/dev/null || true
chown -R mhserver:mhserver "${DATA_DIR}"
chgrp -R mhserver "${WEB_DIR}" 2>/dev/null || true
find "${WEB_DIR}" -type d -exec chmod 775 {} \; 2>/dev/null || true
find "${WEB_DIR}" -type f -exec chmod 664 {} \; 2>/dev/null || true

log "12/12 サービスを有効化・起動"
systemctl daemon-reload
systemctl enable nginx bedrock mhserver-web
systemctl restart nginx
systemctl restart mhserver-web
systemctl start bedrock || true
if [[ -f /etc/systemd/system/appliance-provision.service ]]; then
    systemctl enable appliance-provision.service 2>/dev/null || true
fi

log "セットアップ完了"
echo ""
echo "========================================"
echo " My Craft Server 初期セットアップ完了"
echo "========================================"
echo " シリアル:     ${MASTER_SERIAL}"
echo " ホスト名:     ${HOSTNAME}.local"
echo " 管理画面:     http://${HOSTNAME}.local/"
echo " LAN IP:       $(hostname -I | awk '{print $1}')"
echo ""
echo " 次の作業:"
echo "  1. 出荷時: 管理画面 → OSバージョン15回タップ → 出荷設定"
echo "  2. Cloudflare利用時: ${ETC_DIR}/cloudflare.token と ZONE_ID を設定"
echo "  3. 動作確認: ${BIN_DIR}/shipment-check.sh"
echo ""
if [[ "$SKIP_REBOOT" -eq 0 ]]; then
    echo " 推奨: 再起動して初期状態を確定"
    echo "   sudo reboot"
fi
echo "========================================"
