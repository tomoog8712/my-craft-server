#!/bin/bash
# Cloudflare DNS API helper library

set -euo pipefail

CF_API="https://api.cloudflare.com/client/v4"

_load_settings() {
    local settings="/etc/appliance/settings.conf"
    if [[ ! -f "$settings" ]]; then
        echo "ERROR: $settings not found" >&2
        return 1
    fi
    # shellcheck source=/dev/null
    source "$settings"
}

_get_token() {
    _load_settings || return 1
    if [[ ! -f "${CLOUDFLARE_API_TOKEN_FILE}" ]]; then
        echo "ERROR: Cloudflare token file not found: ${CLOUDFLARE_API_TOKEN_FILE}" >&2
        return 1
    fi
    tr -d '[:space:]' < "${CLOUDFLARE_API_TOKEN_FILE}"
}

_cf_request() {
    local method="$1"
    local endpoint="$2"
    local data="${3:-}"
    local token
    token=$(_get_token) || return 1

    local args=(-s -X "$method" "${CF_API}${endpoint}"
        -H "Authorization: Bearer ${token}"
        -H "Content-Type: application/json")

    if [[ -n "$data" ]]; then
        args+=(-d "$data")
    fi

    local response
    response=$(curl "${args[@]}")
    local success
    success=$(echo "$response" | jq -r '.success // false')

    if [[ "$success" != "true" ]]; then
        echo "ERROR: Cloudflare API failed: $(echo "$response" | jq -r '.errors[0].message // "unknown"')" >&2
        return 1
    fi
    echo "$response"
}

get_public_ipv4() {
    curl -4 -fsSL --max-time 10 https://api.ipify.org 2>/dev/null \
        || curl -4 -fsSL --max-time 10 https://ifconfig.me 2>/dev/null \
        || curl -4 -fsSL --max-time 10 https://icanhazip.com 2>/dev/null
}

serial_to_ddns_label() {
    local serial="$1"
    local prefix="${DDNS_PREFIX:-mc}"
    local lower
    lower=$(echo "$serial" | tr "[:upper:]" "[:lower:]")
    if [[ "$lower" =~ ^mcs-([0-9]{6})$ ]]; then
        echo "${prefix}-mcs${BASH_REMATCH[1]}"
    elif [[ "$lower" =~ ^jrt-([0-9]{6})$ ]]; then
        echo "${prefix}-jrt${BASH_REMATCH[1]}"
    else
        echo "ERROR: unsupported serial format: ${serial}" >&2
        return 1
    fi
}


get_ddns_fqdn() {
    local serial="$1"
    _load_settings || return 1
    local label
    label=$(serial_to_ddns_label "$serial")
    echo "${label}.${DOMAIN_BASE}"
}

find_dns_record() {
    local fqdn="$1"
    _load_settings || return 1
    local response
    response=$(_cf_request GET "/zones/${CLOUDFLARE_ZONE_ID}/dns_records?type=A&name=${fqdn}") || return 1
    echo "$response" | jq -r '.result[0].id // empty'
}

create_dns_record() {
    local fqdn="$1"
    local ip="$2"
    _load_settings || return 1
    local data
    data=$(jq -n --arg type "A" --arg name "$fqdn" --arg content "$ip" --argjson ttl 120 --argjson proxied false \
        '{type: $type, name: $name, content: $content, ttl: $ttl, proxied: $proxied}')
    local response
    response=$(_cf_request POST "/zones/${CLOUDFLARE_ZONE_ID}/dns_records" "$data") || return 1
    echo "$response" | jq -r '.result.id'
}

update_dns_record() {
    local record_id="$1"
    local fqdn="$2"
    local ip="$3"
    _load_settings || return 1
    local data
    data=$(jq -n --arg type "A" --arg name "$fqdn" --arg content "$ip" --argjson ttl 120 --argjson proxied false \
        '{type: $type, name: $name, content: $content, ttl: $ttl, proxied: $proxied}')
    _cf_request PATCH "/zones/${CLOUDFLARE_ZONE_ID}/dns_records/${record_id}" "$data" >/dev/null
}

is_configured() {
    _load_settings || return 1
    [[ -n "${CLOUDFLARE_ZONE_ID}" ]] \
        && [[ -f "${CLOUDFLARE_API_TOKEN_FILE}" ]] \
        && [[ -s "${CLOUDFLARE_API_TOKEN_FILE}" ]] \
        && [[ -n "${DOMAIN_BASE}" ]]
}
