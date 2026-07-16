#!/bin/bash
# First-boot provisioning: register unique DDNS hostname

set -euo pipefail

APPLIANCE_DIR="/etc/appliance"
PROVISIONED="${APPLIANCE_DIR}/.provisioned"
CONFIG="${APPLIANCE_DIR}/config.json"
SERIAL_FILE="${APPLIANCE_DIR}/serial"
UUID_FILE="${APPLIANCE_DIR}/uuid"
LIB="/opt/appliance/lib/cloudflare.sh"

# shellcheck source=/dev/null
source "$LIB"

log() { echo "[provision] $(date -Iseconds) $*"; }

if [[ -f "$PROVISIONED" ]]; then
    log "Already provisioned. Skipping."
    exit 0
fi

if [[ ! -f "$SERIAL_FILE" ]]; then
    log "ERROR: Product serial not found at ${SERIAL_FILE}"
    log "Factory must write serial before shipping (e.g. MCS-000001)"
    exit 1
fi

serial=$(tr -d '[:space:]' < "$SERIAL_FILE")
if [[ ! "$serial" =~ ^(MCS|JRT)-[0-9]{6}$ ]]; then
    log "ERROR: Invalid serial format: ${serial} (expected MCS-000001)"
    exit 1
fi

# Generate internal UUID if not present
if [[ ! -f "$UUID_FILE" ]]; then
    uuidgen | tr '[:upper:]' '[:lower:]' > "$UUID_FILE"
    chmod 440 "$UUID_FILE"
    log "Generated UUID: $(cat "$UUID_FILE")"
fi
uuid=$(cat "$UUID_FILE")

fqdn=$(get_ddns_fqdn "$serial")
product_id="$serial"

if ! is_configured; then
    log "WARN: Cloudflare not configured. Saving pending config."
    jq -n \
        --arg product_id "$product_id" \
        --arg uuid "$uuid" \
        --arg hostname "$fqdn" \
        --arg status "pending_credentials" \
        '{
            product_id: $product_id,
            uuid: $uuid,
            ddns: {
                hostname: $hostname,
                provider: "cloudflare",
                zone_id: "",
                record_id: "",
                last_ip: "",
                last_updated: "",
                status: $status
            }
        }' > "$CONFIG"
    chmod 640 "$CONFIG"
    chown root:appliance "$CONFIG"
    log "Config saved with status=pending_credentials"
    log "Add Cloudflare ZONE_ID and token, then: sudo systemctl start appliance-provision"
    exit 0
fi

_load_settings
current_ip=$(get_public_ipv4 || echo "0.0.0.0")
log "Product: ${product_id}, DDNS: ${fqdn}, IP: ${current_ip}"

record_id=$(find_dns_record "$fqdn" 2>/dev/null || true)
if [[ -z "$record_id" ]]; then
    log "Creating DNS A record for ${fqdn}"
    record_id=$(create_dns_record "$fqdn" "$current_ip")
else
    log "DNS record exists (${record_id}), updating IP"
    update_dns_record "$record_id" "$fqdn" "$current_ip"
fi

jq -n \
    --arg product_id "$product_id" \
    --arg uuid "$uuid" \
    --arg hostname "$fqdn" \
    --arg zone_id "${CLOUDFLARE_ZONE_ID}" \
    --arg record_id "$record_id" \
    --arg last_ip "$current_ip" \
    --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    '{
        product_id: $product_id,
        uuid: $uuid,
        ddns: {
            hostname: $hostname,
            provider: "cloudflare",
            zone_id: $zone_id,
            record_id: $record_id,
            last_ip: $last_ip,
            last_updated: $ts,
            status: "ok"
        }
    }' > "$CONFIG"
chmod 640 "$CONFIG"
chown root:appliance "$CONFIG"

date -u +%Y-%m-%dT%H:%M:%SZ > "$PROVISIONED"
chmod 440 "$PROVISIONED"

log "Provisioning complete: ${fqdn}"
log "External connection: ${fqdn}:${EXTERNAL_PORT:-19134}"
