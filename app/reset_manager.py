"""Reset Center — selective factory-style resets for My Craft Server."""

import ipaddress
import json
import re
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from flask import request

from app.addon_manager import reset_all_addons
from app.discord_manager import DEFAULT_EVENTS, save_event_settings, save_webhook_url
from app.playit_manager import disconnect_playit
from app.player_manager import reset_all_players
from app.support_manager import is_remote_support_active
from app.update_manager import delete_backup, list_backups, wait_for_running
from app.world_manager import WORLDS_DATA, WORLDS_DIR

APPLIANCE_DIR = Path("/etc/appliance")
DATA_DIR = Path("/opt/appliance/data")
MINECRAFT_DIR = Path("/opt/minecraft")
DEFAULT_PROPERTIES = Path("/opt/minecraft-bedrock/server.properties")
REBOOT_SCRIPT = "/opt/appliance/bin/reset-reboot.sh"

_lock = threading.Lock()

RESET_ITEMS = [
    {
        "id": "server_settings",
        "title": "サーバー設定を初期化",
        "description": "server.properties、permissions.json、allowlist.json など Minecraft設定のみ初期化します。ワールドは削除しません。",
        "danger": False,
    },
    {
        "id": "players",
        "title": "プレイヤー管理を初期化",
        "description": "プレイヤー登録、BANリスト、権限設定を初期化します。ワールドは削除しません。",
        "danger": False,
    },
    {
        "id": "addons",
        "title": "アドオンを初期化",
        "description": "インストール済みアドオンと登録情報、バックアップをすべて削除します。ワールドは削除しません。",
        "danger": False,
    },
    {
        "id": "webui",
        "title": "管理画面設定を初期化",
        "description": "WebUIの設定データのみ初期化します。製品情報は保持します。",
        "danger": False,
    },
    {
        "id": "worlds",
        "title": "ワールドを削除",
        "description": "インストールされているすべてのワールドとバックアップを削除します。サーバー設定は保持します。",
        "danger": False,
    },
    {
        "id": "factory",
        "title": "すべて初期化（工場出荷時）",
        "description": "サーバー設定・プレイヤー管理・アドオン・ワールド・バックアップ・Discord・Playit・管理画面設定を初期化します。製品IDとシステムは保持します。",
        "danger": True,
    },
]

PREVIEW_CONTENT = {
    "server_settings": {
        "removed": [
            "server.properties（初期値）",
            "permissions.json",
            "allowlist.json",
        ],
        "kept": [
            "ワールドデータ",
            "プレイヤー管理",
            "アドオン",
            "製品ID",
            "UUID",
            "システム",
            "WebUI",
        ],
    },
    "players": {
        "removed": [
            "プレイヤー登録情報",
            "BANリスト",
            "削除済みプレイヤー記録",
            "permissions.json",
            "allowlist.json",
        ],
        "kept": [
            "ワールドデータ",
            "server.properties",
            "アドオン",
            "製品ID",
            "システム",
            "WebUI",
        ],
    },
    "addons": {
        "removed": [
            "インストール済みアドオン",
            "アドオン登録情報",
            "アドオンバックアップ",
            "操作履歴",
        ],
        "kept": [
            "ワールドデータ",
            "server.properties",
            "プレイヤー管理",
            "製品ID",
            "システム",
            "WebUI",
        ],
    },
    "webui": {
        "removed": [
            "外部接続モード設定",
            "サポート履歴",
            "ポート確認キャッシュ",
            "監視状態データ",
        ],
        "kept": ["製品ID", "UUID", "シリアル番号", "WebUI本体", "システム"],
    },
    "worlds": {
        "removed": [
            "すべてのワールド",
            "ワールドバックアップ",
            "ワールド登録情報",
        ],
        "kept": ["server.properties", "Minecraft設定", "製品ID", "システム", "WebUI"],
    },
    "factory": {
        "removed": [
            "サーバー設定",
            "プレイヤー管理",
            "アドオン",
            "ワールド",
            "バックアップ",
            "Discord設定",
            "Playit設定",
            "Minecraft設定",
            "WebUI設定",
        ],
        "kept": [
            "製品ID",
            "UUID",
            "シリアル番号",
            "システム",
            "WebUI本体",
            "Bedrock本体",
            "リモートサポート機能",
            "診断機能",
            "アップデート機能",
            "Playitプログラム",
        ],
    },
}


def _run(cmd, timeout=60):
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        return 1, "", str(exc)


def _read_file(path):
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError:
        return ""


def _write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _get_admin_code():
    content = _read_file(APPLIANCE_DIR / "settings.conf")
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("RESET_ADMIN_CODE="):
            return line.split("=", 1)[1].strip()
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
    allowed_hosts = {host, "my-craft-server.local", "my-craft-server", "localhost", "127.0.0.1"}
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


def _check_reset_access():
    if not _csrf_ok():
        return False, "リクエストが無効です"
    client = _client_ip()
    if not _is_private_ip(client):
        return False, "リセットはLAN内からのみ実行できます"
    if is_remote_support_active():
        return False, "リモートサポート有効中、またはリモート接続中は実行できません"
    return True, ""


def _validate_admin_code(code):
    expected = _get_admin_code()
    if not expected:
        return False, "初期管理コードが設定されていません"
    if (code or "").strip() != expected:
        return False, "初期管理コードが正しくありません"
    return True, ""


def get_reset_catalog():
    return {
        "items": RESET_ITEMS,
        "admin_code_hint": "初期管理コード",
    }


def preview_reset(reset_id):
    if reset_id not in PREVIEW_CONTENT:
        raise ValueError("不明なリセット項目です")
    content = PREVIEW_CONTENT[reset_id]
    item = next(x for x in RESET_ITEMS if x["id"] == reset_id)
    return {
        "id": reset_id,
        "title": item["title"],
        "description": item["description"],
        "danger": item["danger"],
        "removed": content["removed"],
        "kept": content["kept"],
        "reboot": reset_id == "factory",
    }


def _current_level_name():
    props = _read_file(MINECRAFT_DIR / "server.properties")
    for line in props.splitlines():
        if line.startswith("level-name="):
            return line.split("=", 1)[1].strip()
    return "Bedrock level"


def _reset_server_settings(preserve_level=True):
    if not DEFAULT_PROPERTIES.exists():
        raise RuntimeError("初期設定テンプレートが見つかりません")
    level_name = _current_level_name() if preserve_level else ""
    _stop_and_wait()
    shutil.copy2(DEFAULT_PROPERTIES, MINECRAFT_DIR / "server.properties")
    props_path = MINECRAFT_DIR / "server.properties"
    content = props_path.read_text(encoding="utf-8")
    if preserve_level and level_name:
        if re.search(r"^level-name=", content, flags=re.MULTILINE):
            content = re.sub(
                r"^level-name=.*$",
                f"level-name={level_name}",
                content,
                count=1,
                flags=re.MULTILINE,
            )
        else:
            content += f"\nlevel-name={level_name}\n"
    props_path.write_text(content, encoding="utf-8")
    (MINECRAFT_DIR / "allowlist.json").write_text("[]\n", encoding="utf-8")
    (MINECRAFT_DIR / "permissions.json").write_text("[]\n", encoding="utf-8")
    whitelist = MINECRAFT_DIR / "whitelist.json"
    if whitelist.exists():
        whitelist.write_text("[]\n", encoding="utf-8")
    _start_and_wait()


def _bedrock_ctl(action):
    code, out, err = _run(["sudo", "-n", "/usr/bin/systemctl", action, "bedrock"], timeout=90)
    if code != 0:
        raise RuntimeError(err or out or f"bedrock {action} failed")


def _stop_and_wait():
    _bedrock_ctl("stop")
    time.sleep(2)


def _start_and_wait():
    _bedrock_ctl("start")
    if not wait_for_running():
        raise RuntimeError("サーバーが起動しませんでした")


def _reset_discord():
    save_webhook_url("")
    save_event_settings(dict(DEFAULT_EVENTS))
    history = DATA_DIR / "discord_history.json"
    _write_json(history, {"items": []})
    monitor = DATA_DIR / "discord_monitor.json"
    _write_json(monitor, {
        "last_poll_at": "",
        "connected_players": [],
        "alerts": {},
    })


def _reset_playit():
    ok, msg = disconnect_playit(restart_auth=False)
    if not ok:
        raise RuntimeError(msg or "Playit設定の初期化に失敗しました")
    _write_json(DATA_DIR / "external_connection.json", {
        "mode": "standard",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })


def _reset_players():
    reset_all_players(restart_if_needed=True)


def _reset_addons():
    reset_all_addons(restart=True)


def _reset_webui():
    _write_json(DATA_DIR / "external_connection.json", {
        "mode": "standard",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    _write_json(DATA_DIR / "support_status.json", {
        "enabled": False,
        "enabled_at": "",
        "expires_at": "",
        "duration": "",
        "tailscale_ip": "",
        "connected": False,
        "notification": "idle",
    })
    _write_json(DATA_DIR / "support_history.json", {"entries": []})
    cache = DATA_DIR / "port_check_cache.json"
    if cache.exists():
        cache.unlink()
    _write_json(DATA_DIR / "discord_monitor.json", {
        "last_poll_at": "",
        "connected_players": [],
        "alerts": {},
    })


def _reset_worlds(restart=False):
    _stop_and_wait()
    if WORLDS_DIR.exists():
        for child in WORLDS_DIR.iterdir():
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
    if WORLDS_DATA.exists():
        for child in WORLDS_DATA.iterdir():
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            elif child.is_file():
                child.unlink(missing_ok=True)
    WORLDS_DATA.mkdir(parents=True, exist_ok=True)
    _write_json(WORLDS_DATA / "registry.json", {"active_id": "", "worlds": {}})
    _write_json(WORLDS_DATA / "playtime.json", {})
    if restart:
        _start_and_wait()


def _reset_update_backups():
    for item in list_backups():
        try:
            delete_backup(item["id"])
        except Exception:
            backup_id = item.get("id")
            if not backup_id:
                continue
            for pattern in (f"{backup_id}.tar.gz", f"{backup_id}.meta.json"):
                path = Path("/opt/appliance/backups") / pattern
                path.unlink(missing_ok=True)


def _schedule_reboot():
    code, out, err = _run(["sudo", "-n", REBOOT_SCRIPT], timeout=10)
    if code != 0:
        raise RuntimeError(err or out or "再起動の予約に失敗しました")


def _run_factory_reset():
    """Run all factory steps; continue on error and collect failures."""
    errors = []
    steps = [
        ("ワールド", lambda: _reset_worlds(restart=False)),
        ("サーバー設定", lambda: _reset_server_settings(preserve_level=False)),
        ("プレイヤー", _reset_players),
        ("アドオン", _reset_addons),
        ("Discord", _reset_discord),
        ("Playit", _reset_playit),
        ("管理画面", _reset_webui),
        ("バックアップ", _reset_update_backups),
    ]
    for label, step in steps:
        try:
            step()
        except Exception as exc:
            errors.append(f"{label}: {exc}")
    try:
        _schedule_reboot()
    except Exception as exc:
        errors.append(f"再起動: {exc}")
    return errors


def execute_reset(reset_id, admin_code):
    ok, msg = _validate_admin_code(admin_code)
    if not ok:
        return False, msg, False

    if reset_id not in PREVIEW_CONTENT:
        return False, "不明なリセット項目です", False

    with _lock:
        allowed, msg = _check_reset_access()
        if not allowed:
            return False, msg, False

        try:
            if reset_id == "server_settings":
                _reset_server_settings(preserve_level=True)
            elif reset_id == "players":
                _reset_players()
            elif reset_id == "addons":
                _reset_addons()
            elif reset_id == "webui":
                _reset_webui()
            elif reset_id == "worlds":
                _reset_worlds(restart=False)
                return (
                    True,
                    "ワールドを削除しました。ワールド管理から新しいワールドを作成してからサーバーを起動してください。",
                    False,
                )
            elif reset_id == "factory":
                errors = _run_factory_reset()
                if errors:
                    return (
                        True,
                        "初期化を実行しました。再起動後に一部を確認してください: " + " / ".join(errors),
                        True,
                    )
                return True, "初期化が完了しました。", True
            else:
                return False, "不明なリセット項目です", False
        except Exception as exc:
            return False, str(exc), False

    return True, "初期化が完了しました。", False
