"""Minecraft Bedrock port reachability checks."""

import json
import socket
import struct
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path("/opt/appliance/data")
CACHE_FILE = DATA_DIR / "port_check_cache.json"
CACHE_TTL_SECONDS = 1800
RAKNET_MAGIC = b"\x00\xff\xff\x00\xfe\xfe\xfe\xfe\xfd\xfd\xfd\xfd\x12\x34\x56\x78"


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _now_label():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _read_json(path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default if default is not None else {}


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _http_json(url, timeout=12):
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "MyCraftServer/1.0"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def bedrock_ping(host, port, timeout=2.5):
    """Send RakNet unconnected ping and parse the Bedrock pong."""
    packet = (
        b"\x01"
        + struct.pack(">Q", int(time.time() * 1000) & 0xFFFFFFFFFFFFFFFF)
        + RAKNET_MAGIC
        + RAKNET_MAGIC
    )
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        sock.sendto(packet, (host, int(port)))
        data, _ = sock.recvfrom(4096)
    finally:
        sock.close()

    if not data or data[0] != 0x1C:
        raise OSError("Minecraft応答が不正です")

    text = data.decode("utf-8", errors="ignore")
    marker = "_MCPE;"
    if marker not in text:
        raise OSError("Minecraft応答を解析できませんでした")

    payload = text.split(marker, 1)[1]
    parts = payload.split(";")
    if len(parts) < 5:
        raise OSError("Minecraft応答の形式が不正です")

    return {
        "server_name": parts[0],
        "protocol": parts[1],
        "version": parts[2],
        "players_online": int(parts[3]) if parts[3].isdigit() else 0,
        "players_max": int(parts[4]) if parts[4].isdigit() else 0,
        "bytes": len(data),
    }


def _try_mcsrvstat(host, port):
    if not host:
        return False, {}
    try:
        data = _http_json(f"https://api.mcsrvstat.us/2/{host}:{int(port)}", timeout=12)
        return bool(data.get("online")), data
    except Exception:
        return False, {}


def probe_external_port(host, port, players_online=0):
    if not host:
        raise ValueError("グローバルIPを取得できませんでした")

    port = int(port)
    internal = bedrock_ping("127.0.0.1", port)

    public = None
    public_ok = False
    public_error = ""
    try:
        public = bedrock_ping(host, port)
        public_ok = True
    except OSError as exc:
        public_error = str(exc)

    api_ok, api_data = _try_mcsrvstat(host, port)

    if public_ok:
        external_open = True
        external_status = "ポート開放済み"
        external_summary = (
            f"Minecraft応答あり（{public['players_online']}人 / {public['players_max']}人表示）"
        )
        source = "bedrock_ping_public"
    elif api_ok:
        external_open = True
        external_status = "ポート開放済み"
        players = api_data.get("players", {})
        online = players.get("online", players_online)
        max_players = players.get("max", internal.get("players_max", 10))
        external_summary = f"外部APIから到達確認（{online}人 / {max_players}人）"
        source = "mcsrvstat"
    elif players_online > 0:
        external_open = True
        external_status = "ポート開放済み（接続中）"
        external_summary = (
            f"プレイヤー{players_online}人が接続中・サーバー応答正常"
        )
        source = "active_players"
    else:
        external_open = False
        external_status = "ポート開放されていません"
        if public_error:
            external_summary = f"グローバルIPへMinecraft応答なし（{public_error}）"
        else:
            external_summary = "グローバルIPへMinecraft応答がありません"
        source = "bedrock_ping_public"

    return {
        "checked_at": _now_iso(),
        "checked_label": _now_label(),
        "public_ip": host,
        "external_port": str(port),
        "external_open": external_open,
        "external_status": external_status,
        "external_summary": external_summary,
        "internal_players_online": internal.get("players_online", 0),
        "internal_players_max": internal.get("players_max", 0),
        "public_ping_ok": public_ok,
        "api_online": api_ok,
        "players_online": players_online,
        "source": source,
    }


def load_cached_external_check(max_age_seconds=CACHE_TTL_SECONDS):
    cache = _read_json(CACHE_FILE, {})
    if not cache.get("checked_at"):
        return {}
    try:
        checked = datetime.fromisoformat(cache["checked_at"])
        age = (datetime.now(timezone.utc) - checked).total_seconds()
        cache["cache_age_seconds"] = int(age)
        cache["cache_fresh"] = age <= max_age_seconds
    except ValueError:
        cache["cache_fresh"] = False
    return cache


def save_external_check_result(result):
    _write_json(CACHE_FILE, result)
    return result


def run_external_port_check(host, port, players_online=0):
    result = probe_external_port(host, port, players_online=players_online)
    return save_external_check_result(result)


def get_external_port_status(host, port, refresh=False, players_online=0):
    if refresh:
        return run_external_port_check(host, port, players_online=players_online)
    cache = load_cached_external_check()
    if cache.get("cache_fresh") and str(cache.get("external_port")) == str(port):
        if not host or cache.get("public_ip") == host:
            return cache
    if cache and not refresh:
        stale = dict(cache)
        stale["cache_fresh"] = False
        stale["external_status"] = cache.get("external_status", "未確認")
        stale["external_summary"] = (
            (cache.get("external_summary") or "以前の結果")
            + f"（{cache.get('checked_label', '-')}）"
        )
        return stale
    return {
        "external_open": None,
        "external_status": "未確認",
        "external_summary": "「確認」ボタンで外部ポートをチェックできます",
        "checked_label": "",
    }
