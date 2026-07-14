"""Remote support session management via Tailscale."""

import json
import subprocess
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

DATA_DIR = Path("/opt/appliance/data")
STATUS_FILE = DATA_DIR / "support_status.json"
HISTORY_FILE = DATA_DIR / "support_history.json"

ENABLE_SCRIPT = "/opt/appliance/bin/support-enable.sh"
DISABLE_SCRIPT = "/opt/appliance/bin/support-disable.sh"
STATUS_SCRIPT = "/opt/appliance/bin/support-status.sh"

DURATION_SECONDS = {
    "1h": 3600,
    "24h": 86400,
    "unlimited": None,
}

DURATION_LABELS = {
    "1h": "1時間",
    "24h": "24時間",
    "unlimited": "無期限",
}

_lock = threading.Lock()


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


def _default_status():
    return {
        "enabled": False,
        "enabled_at": None,
        "expires_at": None,
        "duration": None,
        "tailscale_ip": "",
        "connected": False,
        "notification": "idle",
        "updated_at": _now().isoformat(),
    }


def _load_status():
    return _read_json(STATUS_FILE, _default_status())


def _save_status(status):
    status["updated_at"] = _now().isoformat()
    _write_json(STATUS_FILE, status)


def _load_history():
    data = _read_json(HISTORY_FILE, {"entries": []})
    return data.get("entries", [])


def _append_history(message, event="info"):
    entries = _load_history()
    entries.insert(0, {
        "at": _now().isoformat(),
        "event": event,
        "message": message,
        "display_at": _now().astimezone().strftime("%Y-%m-%d %H:%M"),
    })
    entries = entries[:100]
    _write_json(HISTORY_FILE, {"entries": entries})


def _sudo_script(script):
    return _run(["sudo", "-n", script], timeout=60)


def _tailscale_json():
    code, out, _ = _sudo_script(STATUS_SCRIPT)
    if code != 0 or not out:
        return {}
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return {}


def _tailscale_ip():
    data = _tailscale_json()
    self_info = data.get("Self", {})
    ips = self_info.get("TailscaleIPs") or []
    return ips[0] if ips else ""


def _tailscale_online():
    data = _tailscale_json()
    state = data.get("BackendState", "")
    return state in ("Running", "NeedsLogin") and bool(_tailscale_ip())


def _detect_ssh_connected(enabled_at):
    code, out, _ = _run(["who"])
    if code == 0 and out.strip():
        lines = [ln for ln in out.splitlines() if ln.strip()]
        if lines:
            return True

    since = "30 min ago"
    if enabled_at:
        since = enabled_at

    code, out, _ = _run(
        ["journalctl", "-t", "sshd", "--since", since, "-n", "30", "--no-pager", "-o", "cat"],
        timeout=10,
    )
    if code == 0 and out:
        for line in out.splitlines():
            lower = line.lower()
            if "accepted" in lower and ("ssh" in lower or "publickey" in lower):
                return True
    return False


def _remaining_seconds(status):
    expires_at = status.get("expires_at")
    if not expires_at:
        return None
    try:
        expiry = datetime.fromisoformat(expires_at)
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        delta = (expiry - _now()).total_seconds()
        return max(0, int(delta))
    except ValueError:
        return 0


def _remaining_label(seconds):
    if seconds is None:
        return "無期限"
    if seconds <= 0:
        return "0分"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    if hours > 0:
        return f"{hours}時間{minutes}分"
    return f"{minutes}分"


def _maybe_expire(status):
    if not status.get("enabled"):
        return status
    remaining = _remaining_seconds(status)
    if remaining is not None and remaining <= 0:
        expired = _default_status()
        expired["notification"] = "ended"
        _save_status(expired)
        threading.Thread(target=_disable_tailscale_background, daemon=True).start()
        return expired
    return status


def _disable_tailscale_background():
    try:
        _sudo_script(DISABLE_SCRIPT)
    except Exception:
        pass


def _disable_support_unlocked(auto=False):
    status = _load_status()
    if not status.get("enabled") and not auto:
        return False, "すでに無効です"

    code, out, err = _sudo_script(DISABLE_SCRIPT)
    if code != 0 and out != "OK":
        if not auto:
            return False, err or out or "Tailscaleの無効化に失敗しました"

    status = _default_status()
    status["notification"] = "ended"
    _save_status(status)
    msg = "リモートサポート終了（自動）" if auto else "リモートサポート終了"
    _append_history(msg, event="stop")
    return True, "リモートサポートを無効にしました"


def _maybe_log_ssh(status):
    if not status.get("enabled"):
        return status
    connected = _detect_ssh_connected(status.get("enabled_at"))
    was_connected = status.get("connected", False)
    if connected and not was_connected:
        _append_history("SSH接続", event="ssh")
        status["notification"] = "active"
    status["connected"] = connected
    return status


def is_remote_support_active():
    """Return True when remote support is enabled or an SSH session is active."""
    status = _load_status()
    if status.get("enabled"):
        return True
    if status.get("connected"):
        return True
    if _detect_ssh_connected(status.get("enabled_at")):
        return True
    return False


def get_support_status():
    status = _maybe_expire(_load_status())
    with _lock:
        status = _load_status()
        if status.get("enabled"):
            status["tailscale_ip"] = _tailscale_ip()
            status = _maybe_log_ssh(status)
            remaining = _remaining_seconds(status)
            status["remaining_seconds"] = remaining
            status["remaining_label"] = _remaining_label(remaining)
            status["status_label"] = "ON"
            status["connected_label"] = "あり" if status.get("connected") else "なし"
            status["duration_label"] = DURATION_LABELS.get(status.get("duration"), "-")
            if status.get("notification") != "ended":
                status["notification"] = "active"
                status["notification_label"] = "サポート有効"
        else:
            status["remaining_seconds"] = 0
            status["remaining_label"] = "-"
            status["status_label"] = "OFF"
            status["connected"] = False
            status["connected_label"] = "なし"
            status["duration_label"] = "-"
            if status.get("notification") == "ended":
                status["notification_label"] = "サポート終了"
            else:
                status["notification"] = "idle"
                status["notification_label"] = ""
        _save_status(status)
        return {
            **status,
            "history": _load_history()[:20],
            "tailscale_installed": Path("/usr/bin/tailscale").exists(),
        }


def enable_support(duration="1h"):
    if duration not in DURATION_SECONDS:
        return False, "無効な有効時間です"

    with _lock:
        status = _load_status()
        if status.get("enabled"):
            return False, "すでに有効です"

        code, out, err = _sudo_script(ENABLE_SCRIPT)
        if code == 2 or out == "AUTHKEY_MISSING":
            return False, "Tailscale認証キーが未設定です。サポートへご連絡ください。"
        if code != 0 or out != "OK":
            return False, err or out or "Tailscaleの有効化に失敗しました"

        now = _now()
        expires_at = None
        seconds = DURATION_SECONDS[duration]
        if seconds is not None:
            expires_at = (now + timedelta(seconds=seconds)).isoformat()

        status = {
            "enabled": True,
            "enabled_at": now.isoformat(),
            "expires_at": expires_at,
            "duration": duration,
            "tailscale_ip": _tailscale_ip(),
            "connected": False,
            "notification": "active",
            "updated_at": now.isoformat(),
        }
        _save_status(status)
        _append_history("リモートサポート開始", event="start")
        return True, "リモートサポートを有効にしました"


def disable_support(auto=False):
    with _lock:
        return _disable_support_unlocked(auto=auto)


def update_support_time(duration):
    if duration not in DURATION_SECONDS:
        return False, "無効な有効時間です"

    with _lock:
        status = _load_status()
        if not status.get("enabled"):
            return False, "リモートサポートが有効ではありません"

        now = _now()
        seconds = DURATION_SECONDS[duration]
        expires_at = None
        if seconds is not None:
            expires_at = (now + timedelta(seconds=seconds)).isoformat()

        status["duration"] = duration
        status["expires_at"] = expires_at
        _save_status(status)
        _append_history(f"有効時間を{DURATION_LABELS[duration]}に変更", event="time")
        return True, "有効時間を更新しました"
