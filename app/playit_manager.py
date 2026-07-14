"""Playit.gg external connection management."""

import json
import os
import re
import secrets
import subprocess
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from app.port_check_manager import bedrock_ping

DATA_DIR = Path("/opt/appliance/data")
PLAYIT_STATE_FILE = DATA_DIR / "playit.json"
MODE_FILE = DATA_DIR / "external_connection.json"
SECRET_FILE = DATA_DIR / "playit.toml"

INSTALL_SCRIPT = "/opt/appliance/bin/playit-install.sh"
ENABLE_SCRIPT = "/opt/appliance/bin/playit-enable.sh"
DISABLE_SCRIPT = "/opt/appliance/bin/playit-disable.sh"
DISCONNECT_SCRIPT = "/opt/appliance/bin/playit-disconnect.sh"
STATUS_SCRIPT = "/opt/appliance/bin/playit-status.sh"
SAVE_SECRET_SCRIPT = "/opt/appliance/bin/playit-save-secret.sh"
START_AGENT_SCRIPT = "/opt/appliance/bin/playit-start-agent.sh"
CLAIM_EXCHANGE_SCRIPT = "/opt/appliance/bin/playit-claim-exchange.sh"
READ_CLAIM_SECRET_SCRIPT = "/opt/appliance/bin/playit-read-claim-secret.sh"
CREATE_TUNNEL_SCRIPT = "/opt/appliance/bin/playit-create-tunnel.sh"

DEFAULT_BEDROCK_PORT = 19132


def get_bedrock_local_port():
    try:
        from app.settings_manager import read_properties
        _, props = read_properties()
        return int(props.get("server-port", str(DEFAULT_BEDROCK_PORT)))
    except (ValueError, TypeError, OSError):
        return DEFAULT_BEDROCK_PORT


API_BASE = "https://api.playit.gg"
AGENT_VERSION = "my-craft-server-1.0"
CLAIM_URL_BASE = "https://playit.gg/claim/"

STATUS_LABELS = {
    "connected": "接続中",
    "unauthenticated": "未認証",
    "disconnected": "切断",
    "authenticating": "認証待ち",
    "tunnel_pending": "トンネル未設定",
    "error": "エラー",
}

_lock = threading.RLock()
_TUNNEL_CACHE = {"data": None, "fetched_at": 0.0}
_TUNNEL_CACHE_TTL = 60
_CLAIM_POLL_CACHE = {"fetched_at": 0.0, "result": (False, "pending")}
_CLAIM_POLL_MIN_INTERVAL = 10
_ENSURE_CACHE = {"code": "", "fetched_at": 0.0, "ok": False, "error": ""}
_ENSURE_MIN_INTERVAL = 30
_INSTALLED_CACHE = {"value": None, "fetched_at": 0.0}
_INSTALLED_CACHE_TTL = 300


def _now():
    return datetime.now(timezone.utc)


def _run(cmd, timeout=30):
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        return 1, "", str(exc)


def _read_json(path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default if default is not None else {}


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _default_mode():
    return {"mode": "standard", "updated_at": _now().isoformat()}


def _default_playit_state():
    return {
        "enabled": False,
        "installed": False,
        "authenticated": False,
        "status": "disconnected",
        "claim_code": "",
        "claim_url": "",
        "address": "",
        "host": "",
        "port": 19132,
        "endpoint": "",
        "last_error": "",
        "last_test_ok": None,
        "last_test_message": "",
        "updated_at": _now().isoformat(),
    }


def _load_mode():
    return _read_json(MODE_FILE, _default_mode())


def _save_mode(mode):
    data = _default_mode()
    data["mode"] = mode
    data["updated_at"] = _now().isoformat()
    _write_json(MODE_FILE, data)


def _load_state():
    return _read_json(PLAYIT_STATE_FILE, _default_playit_state())


def _save_state(state):
    state["updated_at"] = _now().isoformat()
    _write_json(PLAYIT_STATE_FILE, state)


def _sudo_script(script, *args):
    cmd = ["sudo", "-n", script]
    if args:
        cmd.extend(args)
    return _run(cmd, timeout=90)


def _api_post(path, payload, secret=None, timeout=15):
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "MyCraftServer/1.0",
    }
    if secret:
        headers["Authorization"] = f"agent-key {secret}"
    req = urllib.request.Request(
        f"{API_BASE}{path}",
        data=body,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"status": "error", "data": {"message": raw[:200]}}
    except Exception as exc:
        return {"status": "error", "data": {"message": str(exc)[:200]}}


def _api_success(data):
    return isinstance(data, dict) and data.get("status") == "success"


def _read_secret_from_claim_log(claim_code=""):
    args = (claim_code,) if claim_code else ()
    code, out, _ = _sudo_script(READ_CLAIM_SECRET_SCRIPT, *args)
    if code == 0 and out and out != "NONE":
        return out.strip()
    return ""


def _read_secret():
    if (DATA_DIR / "playit-credentials-cleared").exists():
        return ""
    if SECRET_FILE.exists():
        try:
            text = SECRET_FILE.read_text(encoding="utf-8")
            match = re.search(r'secret_key\s*=\s*"([^"]+)"', text)
            if match:
                return match.group(1)
            match = re.search(r"secret_key\s*=\s*'([^']+)'", text)
            if match:
                return match.group(1)
        except OSError:
            pass
    code, out, _ = _sudo_script(STATUS_SCRIPT, "secret")
    if code == 0 and out and out != "NONE":
        return out.strip()
    return ""


def _service_active():
    code, out, _ = _run(["systemctl", "is-active", "playit"], timeout=5)
    return code == 0 and out == "active"


def _playit_installed():
    now = time.time()
    if (
        _INSTALLED_CACHE["value"] is not None
        and now - float(_INSTALLED_CACHE.get("fetched_at") or 0) < _INSTALLED_CACHE_TTL
    ):
        return _INSTALLED_CACHE["value"]
    code, out, _ = _sudo_script(STATUS_SCRIPT, "installed")
    if code == 0:
        installed = out == "YES"
    else:
        code, out, _ = _run(["which", "playit"], timeout=5)
        installed = code == 0 and bool(out)
    _INSTALLED_CACHE["value"] = installed
    _INSTALLED_CACHE["fetched_at"] = now
    return installed


def _parse_endpoint(address):
    if not address:
        return "", 0, ""
    address = address.strip()
    if "://" in address:
        address = address.split("://", 1)[1]
    if ":" in address:
        host, port_text = address.rsplit(":", 1)
        try:
            port = int(port_text)
        except ValueError:
            host, port = address, 0
    else:
        host, port = address, 19132
    endpoint = f"{host}:{port}" if port else host
    return host, port, endpoint


def _tunnel_display_address(tunnel):
    display = tunnel.get("display_address") or ""
    if display:
        return display
    domain = tunnel.get("assigned_domain") or ""
    port_obj = tunnel.get("port") or {}
    port = port_obj.get("from") or port_obj.get("to") or 0
    if domain and port:
        return f"{domain}:{port}"
    return ""


def _parse_connect_address(value):
    host = value.get("address") or value.get("domain") or ""
    port = 0
    if isinstance(host, str) and host.startswith("[") and "]" in host:
        host_part, rest = host.split("]", 1)
        host = host_part[1:]
        if rest.startswith(":"):
            try:
                port = int(rest[1:])
            except ValueError:
                port = 0
    elif isinstance(host, str) and ":" in host:
        host, port_text = host.rsplit(":", 1)
        try:
            port = int(port_text)
        except ValueError:
            port = 0
    return host, port


def _bedrock_join_address_score(host):
    """Prefer ip.gl.ply.gg for Bedrock join; gl.at.ply.gg often pings but cannot join."""
    host = (host or "").lower().strip()
    if not host:
        return -1
    if re.match(r"^\d+\.\d+\.\d+\.\d+$", host):
        return 0
    if host.endswith(".ip.gl.ply.gg"):
        return 100
    if host.endswith(".gl.at.ply.gg"):
        return 10
    if host.endswith(".ply.gg") or host.endswith(".playit.gg"):
        return 50
    return 30


def _pick_bedrock_join_address(candidates):
    best = None
    best_score = -1
    for host, port, source in candidates:
        score = _bedrock_join_address_score(host)
        if score > best_score:
            best_score = score
            best = (host, port, source)
    return best


def _collect_tunnel_addresses(tunnel):
    tunnel_type = (tunnel.get("tunnel_type") or "").lower()
    candidates = []
    auto_domain = ""

    for alloc in tunnel.get("public_allocations") or []:
        details = alloc.get("details") or {}
        hostname = details.get("ip_hostname") or ""
        auto = details.get("auto_domain") or ""
        port = details.get("port") or 0
        if auto and not auto_domain:
            auto_domain = auto
        if hostname and port:
            candidates.append((hostname, int(port), "ip_hostname"))

    for addr in tunnel.get("connect_addresses") or []:
        host, port = _parse_connect_address(addr.get("value") or {})
        if not host:
            continue
        if addr.get("type") == "addr6":
            continue
        if addr.get("type") == "addr4" and re.match(r"^\d+\.\d+\.\d+\.\d+$", host):
            continue
        source = addr.get("type") or "connect"
        candidates.append((host, port, source))
        if host.endswith(".gl.at.ply.gg") and not auto_domain:
            auto_domain = host

    display = _tunnel_display_address(tunnel)
    if display:
        host, port = _parse_connect_address({"address": display})
        if host:
            candidates.append((host, port, "display"))
            if host.endswith(".gl.at.ply.gg") and not auto_domain:
                auto_domain = host

    picked = _pick_bedrock_join_address(candidates)
    if not picked:
        return None

    host, port, _source = picked
    endpoint = f"{host}:{port}" if port else host
    item = {
        "address": endpoint,
        "tunnel_type": tunnel_type,
        "join_host": host,
        "auto_domain": auto_domain if auto_domain and auto_domain != host else "",
        "local_ip": tunnel.get("local_ip") or "",
        "local_port": tunnel.get("local_port") or 0,
    }
    return item


def _extract_tunnel_from_rundata(data):
    tunnels = data.get("tunnels") or []
    preferred = None
    fallback = None
    for tunnel in tunnels:
        tunnel_type = (tunnel.get("tunnel_type") or "").lower()
        item = _collect_tunnel_addresses(tunnel)
        if not item:
            continue
        if "bedrock" in tunnel_type:
            preferred = item
            break
        if tunnel_type in ("minecraft-java", "") and not fallback:
            fallback = item
        if not fallback:
            fallback = item
    return preferred or fallback


def _tunnel_cache_valid():
    if not _TUNNEL_CACHE.get("data"):
        return False
    age = time.time() - float(_TUNNEL_CACHE.get("fetched_at") or 0)
    return age < _TUNNEL_CACHE_TTL


def _store_tunnel_cache(tunnel):
    if tunnel:
        _TUNNEL_CACHE["data"] = dict(tunnel)
        _TUNNEL_CACHE["fetched_at"] = time.time()


def _fetch_tunnel_address(secret, force=False):
    if not secret:
        return None
    if not force and _tunnel_cache_valid():
        return dict(_TUNNEL_CACHE["data"])

    listing = _api_post("/v1/tunnels/list", {}, secret=secret)
    listing_tunnels = []
    if _api_success(listing):
        listing_tunnels = (listing.get("data") or {}).get("tunnels") or []

    for tunnel in listing_tunnels:
        tunnel_type = (tunnel.get("tunnel_type") or "").lower()
        if "bedrock" in tunnel_type:
            found = _collect_tunnel_addresses(tunnel)
            if found:
                origin = (tunnel.get("origin") or {}).get("details") or {}
                config = origin.get("config_data") or {}
                for field in config.get("fields") or []:
                    name = field.get("name") or ""
                    value = field.get("value") or ""
                    if name == "local_ip" and value:
                        found["local_ip"] = value
                    if name == "local_port" and value:
                        try:
                            found["local_port"] = int(value)
                        except ValueError:
                            found["local_port"] = value
                _store_tunnel_cache(found)
                return found

    for tunnel in listing_tunnels:
        found = _collect_tunnel_addresses(tunnel)
        if found:
            _store_tunnel_cache(found)
            return found

    rundata = _api_post("/agents/rundata", {}, secret=secret)
    if _api_success(rundata):
        found = _extract_tunnel_from_rundata(rundata.get("data") or {})
        if found:
            _store_tunnel_cache(found)
        return found
    return None


def _journal_claim_url():
    code, out, _ = _run(
        ["journalctl", "-u", "playit", "-n", "80", "--no-pager", "-o", "cat"],
        timeout=10,
    )
    if code != 0 or not out:
        return ""
    for pattern in (
        r"https://playit\.gg/claim/[A-Za-z0-9]+",
        r"https://playit\.gg/mc/[A-Za-z0-9]+",
    ):
        match = re.search(pattern, out)
        if match:
            return match.group(0)
    return ""


def _journal_tunnel_address():
    code, out, _ = _run(
        ["journalctl", "-u", "playit", "-n", "120", "--no-pager", "-o", "cat"],
        timeout=10,
    )
    if code != 0 or not out:
        return ""
    patterns = [
        r"\d+\.ip\.gl\.ply\.gg:\d+",
        r"[A-Za-z0-9][A-Za-z0-9.-]*\.ip\.gl\.ply\.gg:\d+",
        r"[A-Za-z0-9][A-Za-z0-9.-]*\.gl\.at\.ply\.gg:\d+",
        r"[A-Za-z0-9][A-Za-z0-9.-]*\.playit\.gg:\d+",
        r"[A-Za-z0-9][A-Za-z0-9.-]*\.ply\.gg:\d+",
    ]
    for pattern in patterns:
        matches = re.findall(pattern, out)
        if matches:
            return matches[-1]
    return ""


def _ensure_claim_agent_running(code):
    """Keep playitd and claim exchange alive during browser authentication."""
    if not code:
        return False, "認証コードがありません"

    if _service_active() and _claim_exchange_running(code):
        _ENSURE_CACHE.update({"code": code, "fetched_at": time.time(), "ok": True, "error": ""})
        return True, "OK"

    now = time.time()
    if (
        _ENSURE_CACHE.get("code") == code
        and now - float(_ENSURE_CACHE.get("fetched_at") or 0) < _ENSURE_MIN_INTERVAL
        and not _ENSURE_CACHE.get("ok")
    ):
        return False, _ENSURE_CACHE.get("error") or "エージェントを起動しています…"

    start_code, start_out, start_err = _sudo_script(START_AGENT_SCRIPT)
    if start_code != 0 and start_out not in ("OK",):
        msg = start_err or start_out or "Playit Agentの起動に失敗しました"
        _ENSURE_CACHE.update({"code": code, "fetched_at": now, "ok": False, "error": msg})
        return False, msg

    ex_code, ex_out, ex_err = _sudo_script(CLAIM_EXCHANGE_SCRIPT, code)
    if ex_code != 0 and ex_out not in ("OK", "ALREADY"):
        msg = ex_err or ex_out or "認証待受の開始に失敗しました"
        _ENSURE_CACHE.update({"code": code, "fetched_at": now, "ok": False, "error": msg})
        return False, msg

    ok = _service_active() and _claim_exchange_running(code)
    _ENSURE_CACHE.update({
        "code": code,
        "fetched_at": now,
        "ok": ok,
        "error": "" if ok else "エージェントを起動しています…",
    })
    if ok:
        return True, "OK"
    return False, _ENSURE_CACHE["error"]


def _process_alive(pid):
    try:
        return Path(f"/proc/{int(pid)}").exists()
    except (TypeError, ValueError):
        return False


def _claim_exchange_running(code):
    code_file = DATA_DIR / "playit-claim-exchange.code"
    legacy_code = Path("/run/playit/claim-exchange.code")
    if not code_file.exists() and legacy_code.exists():
        code_file = legacy_code
    if not code_file.exists():
        return False
    try:
        saved_code = code_file.read_text(encoding="utf-8").strip()
        if saved_code != code:
            return False
    except OSError:
        return False
    run_code, out, _ = _run(["pgrep", "-f", f"claim exchange {code}"], timeout=5)
    return run_code == 0 and bool(out.strip())


def _ensure_installed():
    if _playit_installed():
        return True, "インストール済み"
    code, out, err = _sudo_script(INSTALL_SCRIPT)
    if code != 0:
        return False, err or out or "Playitのインストールに失敗しました"
    return True, "Playitをインストールしました"


def _start_claim():
    code = secrets.token_hex(8)
    setup = _api_post(
        "/claim/setup",
        {
            "code": code,
            "agent_type": "self-managed",
            "version": AGENT_VERSION,
        },
    )
    if not _api_success(setup):
        detail = setup.get("data")
        if isinstance(detail, str):
            msg = detail
        else:
            msg = (detail or {}).get("message") or "認証の開始に失敗しました"
        return False, msg

    claim_url = f"{CLAIM_URL_BASE}{code}"
    state = _load_state()
    state.update({
        "status": "authenticating",
        "claim_code": code,
        "claim_url": claim_url,
        "last_error": "",
        "claim_agent_ready": False,
    })
    _save_state(state)
    ok, msg = _ensure_claim_agent_running(code)
    if not ok:
        state["last_error"] = msg
        _save_state(state)
        return False, msg
    return True, claim_url


def _secret_valid(secret):
    if not secret:
        return False
    result = _api_post("/agents/rundata", {}, secret=secret, timeout=8)
    return _api_success(result)


def _poll_claim_exchange():
    state = _load_state()
    code = state.get("claim_code")
    if not code:
        secret = _read_secret()
        if secret and _secret_valid(secret):
            state["authenticated"] = True
            state["status"] = "connected"
            state["claim_code"] = ""
            state["claim_url"] = ""
            state["last_error"] = ""
            _save_state(state)
            _sudo_script(ENABLE_SCRIPT)
            return True, secret
        return False, "認証コードがありません"

    agent_ok, agent_msg = (True, "OK")
    if not (_service_active() and _claim_exchange_running(code)):
        agent_ok, agent_msg = _ensure_claim_agent_running(code)
        if not agent_ok:
            state["last_error"] = agent_msg
            _save_state(state)
            return False, agent_msg

    result = _api_post("/claim/exchange", {"code": code}, timeout=8)
    if not _api_success(result):
        detail = result.get("data")
        if isinstance(detail, str):
            if detail in ("CodeNotFound", "NotAccepted", "NotSetup", "WaitingForUser"):
                secret = _read_secret_from_claim_log(code)
                if secret:
                    save_code, save_out, save_err = _sudo_script(SAVE_SECRET_SCRIPT, secret)
                    if save_code == 0 and save_out == "OK":
                        state["authenticated"] = True
                        state["status"] = "connected"
                        state["claim_code"] = ""
                        state["claim_url"] = ""
                        state["last_error"] = ""
                        _save_state(state)
                        _sudo_script(ENABLE_SCRIPT)
                        return True, secret
                return False, "pending"
            return False, detail
        if isinstance(detail, dict):
            msg = detail.get("message") or detail.get("error") or "pending"
            if msg in ("CodeNotFound", "NotAccepted", "NotSetup", "WaitingForUser"):
                secret = _read_secret_from_claim_log(code)
                if secret:
                    save_code, save_out, save_err = _sudo_script(SAVE_SECRET_SCRIPT, secret)
                    if save_code == 0 and save_out == "OK":
                        state["authenticated"] = True
                        state["status"] = "connected"
                        state["claim_code"] = ""
                        state["claim_url"] = ""
                        state["last_error"] = ""
                        _save_state(state)
                        _sudo_script(ENABLE_SCRIPT)
                        return True, secret
                return False, "pending"
            return False, msg
        return False, "pending"

    secret = (result.get("data") or {}).get("secret_key")
    if not secret:
        return False, "pending"

    save_code, save_out, save_err = _sudo_script(SAVE_SECRET_SCRIPT, secret)
    if save_code != 0 or save_out != "OK":
        return False, save_err or save_out or "秘密鍵の保存に失敗しました"

    state["authenticated"] = True
    state["status"] = "connected"
    state["claim_code"] = ""
    state["claim_url"] = ""
    state["last_error"] = ""
    _save_state(state)

    _sudo_script(ENABLE_SCRIPT)
    return True, secret


def _poll_claim_exchange_throttled():
    now = time.time()
    age = now - float(_CLAIM_POLL_CACHE.get("fetched_at") or 0)
    if age < _CLAIM_POLL_MIN_INTERVAL and _CLAIM_POLL_CACHE.get("result") is not None:
        return _CLAIM_POLL_CACHE["result"]
    result = _poll_claim_exchange()
    _CLAIM_POLL_CACHE["fetched_at"] = now
    _CLAIM_POLL_CACHE["result"] = result
    return result


def _resolve_status_quick(state, secret):
    state["installed"] = state.get("installed", _playit_installed())
    state["enabled"] = bool(state.get("enabled"))
    state["authenticated"] = bool(secret) and _secret_valid(secret)
    state["service_active"] = _service_active()
    state["status_label"] = STATUS_LABELS.get(state.get("status"), state.get("status", "-"))
    return state


def _create_bedrock_tunnel(local_ip="127.0.0.1", local_port=None):
    if local_port is None:
        local_port = get_bedrock_local_port()
    code, out, err = _sudo_script(CREATE_TUNNEL_SCRIPT, local_ip, str(local_port))
    if code == 0 and out in ("OK", "ALREADY"):
        _TUNNEL_CACHE["fetched_at"] = 0
        return True, "Bedrockトンネルを作成しました"
    if out == "NOT_AUTHENTICATED":
        return False, "Playitが未認証です"
    if out == "AGENT_NOT_READY":
        return False, "Playit Agentの準備ができていません。数十秒後に再試行してください"
    return False, err or out or "トンネル作成に失敗しました"


def _maybe_create_tunnel(secret, state):
    if not secret or not _service_active():
        return False, "pending"
    if state.get("endpoint") or state.get("address"):
        return True, "ready"
    tunnel = _fetch_tunnel_address(secret)
    if tunnel:
        return True, "ready"
    return _create_bedrock_tunnel(local_port=get_bedrock_local_port())


def _clear_stale_playit_error(state, authenticated):
    last_error = state.get("last_error") or ""
    if not last_error:
        return
    if authenticated and (
        last_error.startswith("install:")
        or "chmod failed" in last_error
        or "Read-only file system" in last_error
    ):
        state["last_error"] = ""


def _resolve_status(state, secret):
    installed = _playit_installed()
    active = _service_active()
    authenticated = bool(secret)

    address = state.get("address") or ""
    host = state.get("host") or ""
    port = state.get("port") or 19132
    endpoint = state.get("endpoint") or ""

    if authenticated and active:
        tunnel = None
        if state.get("endpoint") or state.get("address"):
            if _tunnel_cache_valid():
                tunnel = dict(_TUNNEL_CACHE["data"])
        if not tunnel:
            tunnel = _fetch_tunnel_address(secret)
        if not tunnel:
            journal_addr = _journal_tunnel_address()
            if journal_addr:
                tunnel = {"address": journal_addr, "tunnel_type": ""}
        if tunnel:
            host, port, endpoint = _parse_endpoint(tunnel.get("address", ""))
            address = tunnel.get("address", endpoint)
            state["address"] = address
            state["host"] = host
            state["port"] = port or 19132
            state["endpoint"] = endpoint
            state["join_host"] = tunnel.get("join_host") or host
            state["auto_domain"] = tunnel.get("auto_domain") or ""
            state["tunnel_type"] = tunnel.get("tunnel_type") or ""
            state["status"] = "connected"
        elif state.get("status") == "authenticating":
            pass
        elif authenticated:
            if not (state.get("endpoint") or state.get("address")):
                state["status"] = "tunnel_pending"
            else:
                state["status"] = "connected" if active else "disconnected"
    elif state.get("status") == "authenticating":
        pass
    elif not authenticated:
        state["status"] = "unauthenticated"
        claim_url = state.get("claim_url") or _journal_claim_url()
        if claim_url and not state.get("claim_url"):
            state["claim_url"] = claim_url
    elif not active:
        state["status"] = "disconnected"
    else:
        state["status"] = "error"

    if state.get("last_error") and state.get("status") not in (
        "connected",
        "authenticating",
        "tunnel_pending",
    ):
        state["status"] = "error"

    _clear_stale_playit_error(state, authenticated)

    state["installed"] = installed
    state["enabled"] = bool(state.get("enabled")) or (active and authenticated)
    state["authenticated"] = authenticated
    state["service_active"] = active
    if authenticated:
        state["claim_code"] = ""
        state["claim_url"] = ""
        if state.get("status") == "connected":
            state["last_error"] = ""
    state["status_label"] = STATUS_LABELS.get(state.get("status"), state.get("status", "-"))
    _save_state(state)
    return state


def get_playit_status(force_refresh=False, poll_claim=True):
    with _lock:
        mode = _load_mode()
        state = _load_state()
        secret = _read_secret()
        if secret and not _secret_valid(secret) and not state.get("claim_code"):
            secret = ""
        if force_refresh:
            _TUNNEL_CACHE["fetched_at"] = 0

        pending_auth = bool(state.get("claim_code")) and not secret
        if pending_auth and state.get("status") == "error":
            state["status"] = "authenticating"
            state["last_error"] = ""

        if pending_auth and state.get("status") == "authenticating":
            code = state.get("claim_code")
            claim_agent_ready = _service_active() and _claim_exchange_running(code)
            if poll_claim:
                if not claim_agent_ready:
                    agent_ok, agent_msg = _ensure_claim_agent_running(code)
                    claim_agent_ready = agent_ok and _service_active() and _claim_exchange_running(code)
                    if not agent_ok:
                        state["last_error"] = agent_msg
                else:
                    state["last_error"] = ""
                    state["status"] = "authenticating"
                state["claim_agent_ready"] = claim_agent_ready
                _save_state(state)
                ok, result = _poll_claim_exchange_throttled()
                if ok:
                    secret = result if isinstance(result, str) else _read_secret()
                elif result != "pending":
                    err = str(result)
                    if err not in ("CodeNotFound", "NotAccepted", "NotSetup", "WaitingForUser"):
                        state["last_error"] = err
                        if "chmod failed" not in err and "Read-only file system" not in err:
                            state["status"] = "error"
            else:
                state["claim_agent_ready"] = claim_agent_ready
                state["status_label"] = STATUS_LABELS.get(state.get("status"), state.get("status", "-"))

        if force_refresh and secret:
            _fetch_tunnel_address(secret, force=True)
        if poll_claim:
            state = _resolve_status(state, secret)
            has_endpoint = bool(state.get("endpoint") or state.get("address"))
            if secret and not has_endpoint and state.get("status") != "authenticating":
                ok, msg = _maybe_create_tunnel(secret, state)
                if ok and msg == "ready":
                    state = _resolve_status(state, secret)
                elif not ok and msg != "pending":
                    state["last_error"] = msg
                    _save_state(state)
        else:
            state = _resolve_status_quick(state, secret)
        host = state.get("host") or ""
        port = state.get("port") or 19132
        endpoint = state.get("endpoint") or (f"{host}:{port}" if host else "")
        has_endpoint = bool(state.get("endpoint") or state.get("address"))
        if state.get("claim_url"):
            setup_phase = "auth"
        elif secret and not has_endpoint:
            setup_phase = "tunnel"
        elif secret and has_endpoint:
            setup_phase = "ready"
        else:
            setup_phase = "auth"

        is_ready = (
            state.get("status") == "connected"
            and bool(state.get("endpoint") or state.get("address"))
        )

        return {
            **state,
            "is_ready": is_ready,
            "endpoint": endpoint,
            "setup_phase": setup_phase,
            "playit_dashboard_url": "https://playit.gg/account/tunnels",
            "qr_url": (
                "https://api.qrserver.com/v1/create-qr-code/?size=180x180&data="
                + urllib.request.quote(state.get("claim_url") or "")
            ) if state.get("claim_url") else "",
        }


def start_playit_login():
    with _lock:
        ok, msg = _ensure_installed()
        if not ok:
            return False, msg

        secret = _read_secret()
        if secret:
            _sudo_script(ENABLE_SCRIPT)
            state = _load_state()
            state["authenticated"] = True
            state["status"] = "tunnel_pending" if not (state.get("endpoint") or state.get("address")) else "connected"
            state["last_error"] = ""
            _save_state(state)
            if state["status"] == "tunnel_pending":
                return True, "認証済みです。Playit.ggでBedrockトンネルを作成してください"
            return True, "すでに認証済みです"

        ok, msg = _start_claim()
        if not ok:
            state = _load_state()
            state["status"] = "error"
            state["last_error"] = msg
            _save_state(state)
            return False, msg
        return True, msg


def test_playit_connection():
    with _lock:
        state = _load_state()
        secret = _read_secret()
        state = _resolve_status(state, secret)
        host = state.get("host")
        port = int(state.get("port") or 19132)

        if not host:
            state["last_test_ok"] = False
            state["last_test_message"] = "Playitアドレスが未設定です"
            _save_state(state)
            return False, state["last_test_message"]

        if not _service_active():
            state["last_test_ok"] = False
            state["last_test_message"] = "Playit Agentが停止しています"
            _save_state(state)
            return False, state["last_test_message"]

        try:
            result = bedrock_ping(host, port)
            players = result.get("players_online", 0)
            max_players = result.get("players_max", 0)
            msg = f"接続成功（{players}人 / {max_players}人）"
            state["last_test_ok"] = True
            state["last_test_message"] = msg
            state["status"] = "connected"
            _save_state(state)
            return True, msg
        except Exception as exc:
            msg = f"接続テスト失敗: {str(exc)[:120]}"
            state["last_test_ok"] = False
            state["last_test_message"] = msg
            state["status"] = "error"
            state["last_error"] = msg
            _save_state(state)
            return False, msg


def enable_playit(mode=None):
    """Start Playit agent / setup. Port forwarding is unaffected."""
    with _lock:
        ok, msg = _ensure_installed()
        if not ok:
            return False, msg

        secret = _read_secret()
        if secret:
            code, out, err = _sudo_script(ENABLE_SCRIPT)
            if code != 0 and out != "OK":
                return False, err or out or "Playit Agentの起動に失敗しました"
        else:
            ok, msg = _start_claim()
            if not ok:
                return False, msg

        state = _load_state()
        state["enabled"] = True
        state["status"] = "authenticating" if not secret else "connected"
        state["last_error"] = ""
        _save_state(state)
        return True, "Playit.ggを開始しました"


def disable_playit():
    """Stop Playit agent only. Port forwarding is unaffected."""
    with _lock:
        code, out, err = _sudo_script(DISABLE_SCRIPT)
        if code != 0 and out != "OK":
            return False, err or out or "Playit Agentの停止に失敗しました"

        state = _load_state()
        state["enabled"] = False
        state["status"] = "disconnected" if _read_secret() else "unauthenticated"
        _save_state(state)
        return True, "Playit Agentを停止しました"


def disconnect_playit(restart_auth=True):
    """Stop agent, remove credentials, and reset local state for a fresh Playit setup."""
    with _lock:
        code, out, err = _sudo_script(DISCONNECT_SCRIPT)
        if code != 0 and out != "OK":
            return False, err or out or "Playitの接続解除に失敗しました"

        _TUNNEL_CACHE["data"] = None
        _TUNNEL_CACHE["fetched_at"] = 0
        _CLAIM_POLL_CACHE["fetched_at"] = 0.0
        _CLAIM_POLL_CACHE["result"] = (False, "pending")
        _ENSURE_CACHE.update({"code": "", "fetched_at": 0.0, "ok": False, "error": ""})

        state = _default_playit_state()
        state["installed"] = _playit_installed()
        state["enabled"] = False
        state["status"] = "unauthenticated"
        _save_state(state)

        if restart_auth and mode.get("mode") == "playit":
            ok, msg = _start_claim()
            if ok:
                return True, "接続を解除しました。新しい認証URLを表示しています"
            state = _load_state()
            state["last_error"] = msg
            _save_state(state)
            return True, f"接続を解除しました（認証の再開に失敗: {msg}）"

        return True, "Playitの接続を解除しました。「認証を開始」から再セットアップできます"


def create_playit_tunnel(local_ip="127.0.0.1", local_port=None):
    if local_port is None:
        local_port = get_bedrock_local_port()
    with _lock:
        secret = _read_secret()
        if not secret:
            return False, "Playitが未認証です"
        if not _service_active():
            _sudo_script(ENABLE_SCRIPT)
            time.sleep(2)
        ok, msg = _create_bedrock_tunnel(local_ip, local_port)
        if not ok:
            return False, msg
        state = _load_state()
        state = _resolve_status(state, secret)
        if state.get("endpoint") or state.get("address"):
            return True, "Bedrockトンネルを作成しました"
        return True, msg


def save_external_mode(mode):
    if mode == "playit":
        return enable_playit()
    if mode == "standard":
        return disable_playit()
    return False, "無効な接続方式です"
