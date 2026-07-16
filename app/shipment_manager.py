"""Shipment setup flow — factory init, serial assignment, QA check."""

import ipaddress
import re
import subprocess
import threading
import time
from pathlib import Path

from flask import request

from app.reset_manager import SHIPMENT_INIT_STEPS, run_shipment_init_step

APPLIANCE_DIR = Path("/etc/appliance")
SHIPMENT_PASSWORD = "8712"
SERIAL_PATTERN = re.compile(r"^(MCS|JRT)-(\d{6})$")
APPLY_SERIAL_SCRIPT = "/opt/appliance/bin/shipment-apply-serial.sh"
PRIV_EXEC_SCRIPT = "/opt/appliance/bin/priv-exec.sh"

_auth_until = 0.0
_lock = threading.Lock()


def _run(cmd, timeout=120):
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        return 1, "", str(exc)


def _read_file(path):
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _client_ip():
    real_ip = request.headers.get("X-Real-IP", "").strip()
    if real_ip:
        return real_ip
    forwarded = request.headers.get("X-Forwarded-For", "").strip()
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or ""


def _is_private_ip(ip_str):
    try:
        ip = ipaddress.ip_address(ip_str)
        return ip.is_loopback or ip.is_private
    except ValueError:
        return False


def _csrf_ok():
    host = (request.host or "").split(":")[0].lower()
    allowed_hosts = {host, "my-craft-server.local", "my-craft-server", "my-craft-server-master.local", "my-craft-server-master", "localhost", "127.0.0.1"}
    origin = request.headers.get("Origin", "").strip()
    if origin:
        from urllib.parse import urlparse
        parsed = urlparse(origin)
        if parsed.hostname and (
            parsed.hostname.lower() in allowed_hosts or _is_private_ip(parsed.hostname)
        ):
            return True
        return False
    referer = request.headers.get("Referer", "").strip()
    if referer:
        from urllib.parse import urlparse
        parsed = urlparse(referer)
        if parsed.hostname and (
            parsed.hostname.lower() in allowed_hosts or _is_private_ip(parsed.hostname)
        ):
            return True
        return False
    return request.method == "GET"


def _check_access():
    if not _csrf_ok():
        return False, "リクエストが無効です"
    client = _client_ip()
    if not _is_private_ip(client):
        return False, "出荷設定はLAN内からのみ実行できます"
    return True, ""


def is_shipment_authenticated():
    return time.time() < _auth_until


def authenticate(password):
    global _auth_until
    allowed, msg = _check_access()
    if not allowed:
        return False, msg
    if (password or "").strip() != SHIPMENT_PASSWORD:
        return False, "パスワードが正しくありません"
    with _lock:
        _auth_until = time.time() + 3600
    return True, ""


def require_auth():
    if not is_shipment_authenticated():
        return False, "認証が必要です"
    allowed, msg = _check_access()
    if not allowed:
        return False, msg
    return True, ""


def get_init_step_definitions():
    return [{"id": step_id, "label": label} for step_id, label in SHIPMENT_INIT_STEPS]


def get_current_serial():
    serial = _read_file(APPLIANCE_DIR / "serial")
    return serial if serial else "未設定"


def validate_serial(serial):
    value = (serial or "").strip().upper()
    if not SERIAL_PATTERN.match(value):
        return False, "MCS-000001 形式（6桁）で入力してください", ""
    return True, "", value


def execute_init_step(step_id):
    ok, msg = require_auth()
    if not ok:
        return False, msg
    valid_ids = {step_id for step_id, _ in SHIPMENT_INIT_STEPS}
    if step_id not in valid_ids:
        return False, "不明な初期化ステップです"
    with _lock:
        ok, msg = require_auth()
        if not ok:
            return False, msg
        try:
            run_shipment_init_step(step_id)
            return True, "OK"
        except Exception as exc:
            return False, str(exc)


def execute_serial_update(serial):
    ok, msg = require_auth()
    if not ok:
        return False, msg, ""
    valid, msg, value = validate_serial(serial)
    if not valid:
        return False, msg, ""
    with _lock:
        ok, msg = require_auth()
        if not ok:
            return False, msg, ""
        code, out, err = _run(
            ["sudo", "-n", PRIV_EXEC_SCRIPT, APPLY_SERIAL_SCRIPT, value],
            timeout=180,
        )
        if code != 0:
            return False, err or out or "シリアル番号の更新に失敗しました", ""
        return True, f"シリアル番号を {value} に設定しました", value


def execute_finalize():
    """Ensure bedrock is running after shipment setup."""
    ok, msg = require_auth()
    if not ok:
        return False, msg
    with _lock:
        code, out, err = _run(
            ["sudo", "-n", "/usr/bin/systemctl", "start", "bedrock"],
            timeout=90,
        )
        if code != 0:
            return False, err or out or "bedrock の起動に失敗しました"
    return True, "OK"
