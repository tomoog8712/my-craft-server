"""Minecraft Bedrock one-click update, backup, and restore."""

import json
import os
import re
import shutil
import subprocess
import tarfile
import threading
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

MINECRAFT_DIR = Path("/opt/minecraft")
BACKUP_DIR = Path("/opt/appliance/backups")
DATA_DIR = Path("/opt/appliance/data")
WORK_DIR = Path("/opt/appliance/work")
STATUS_FILE = DATA_DIR / "update_status.json"
HISTORY_FILE = DATA_DIR / "update_history.json"
VERSION_FILE = DATA_DIR / "bedrock_version.json"
LOCK_FILE = DATA_DIR / "update.lock"

API_URL = "https://net-secondary.web.minecraft-services.net/api/v1.0/download/links"
MAX_BACKUPS = 10
POLL_START_SECONDS = 2
POLL_START_ATTEMPTS = 60

PRESERVE_NAMES = {
    "worlds",
    "server.properties",
    "allowlist.json",
    "permissions.json",
    "whitelist.json",
}

BACKUP_ITEMS = [
    "worlds",
    "server.properties",
    "allowlist.json",
    "permissions.json",
    "whitelist.json",
]

VERSION_RE = re.compile(r"bedrock-server-([\d.]+)\.zip", re.I)
JOURNAL_VERSION_RE = re.compile(r"Version:\s*([\d.]+)")

_update_lock = threading.Lock()


def _now_id():
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _run(cmd, timeout=300):
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def _systemctl(action):
    code, out, err = _run(["sudo", "-n", "/usr/bin/systemctl", action, "bedrock"], timeout=60)
    return code == 0, err or out


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read_json(path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default if default is not None else {}


def _set_status(state, step=None, message="", extra=None):
    payload = {
        "state": state,
        "step": step,
        "message": message,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if extra:
        payload.update(extra)
    _write_json(STATUS_FILE, payload)


def get_update_status():
    return _read_json(STATUS_FILE, {"state": "idle", "step": None, "message": ""})


def _parse_version_tuple(version):
    parts = []
    for piece in str(version).split("."):
        try:
            parts.append(int(piece))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def compare_versions(left, right):
    return (_parse_version_tuple(left) > _parse_version_tuple(right)) - (
        _parse_version_tuple(left) < _parse_version_tuple(right)
    )


def fetch_latest_release():
    req = urllib.request.Request(API_URL, headers={"User-Agent": "MyCraftServer/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    for link in data.get("result", {}).get("links", []):
        if link.get("downloadType") == "serverBedrockLinux":
            url = link.get("downloadUrl", "")
            match = VERSION_RE.search(url)
            if match:
                return match.group(1), url
    raise RuntimeError("Latest Bedrock Linux download link not found")


def get_installed_version():
    saved = _read_json(VERSION_FILE, {})
    if saved.get("version"):
        return saved["version"]

    code, out, _ = _run(
        ["journalctl", "-u", "bedrock", "-n", "300", "--no-pager", "-o", "cat"],
        timeout=15,
    )
    if code == 0:
        for line in reversed(out.splitlines()):
            match = JOURNAL_VERSION_RE.search(line)
            if match:
                return match.group(1)
    return "unknown"


def save_installed_version(version):
    _write_json(
        VERSION_FILE,
        {"version": version, "updated_at": datetime.now(timezone.utc).isoformat()},
    )


def get_backup_archive_path(backup_id):
    if not re.fullmatch(r"\d{8}-\d{6}", backup_id):
        raise ValueError("Invalid backup id")
    return _backup_archive_path(backup_id)


def get_update_info():
    current = get_installed_version()
    if not VERSION_FILE.exists() and current != "unknown":
        save_installed_version(current)
    try:
        latest, download_url = fetch_latest_release()
        latest_error = ""
    except Exception as exc:
        latest, download_url = current, ""
        latest_error = str(exc)

    has_update = bool(latest and current != "unknown" and compare_versions(latest, current) > 0)
    return {
        "current_version": current,
        "latest_version": latest,
        "download_url": download_url,
        "has_update": has_update,
        "status_label": "アップデートがあります" if has_update else "最新版です",
        "latest_error": latest_error,
        "history": get_update_history(),
    }


def _backup_meta_path(backup_id):
    return BACKUP_DIR / f"{backup_id}.meta.json"


def _backup_archive_path(backup_id):
    return BACKUP_DIR / f"{backup_id}.tar.gz"


def _format_size(num_bytes):
    if num_bytes < 1024 * 1024:
        return f"{max(1, num_bytes // 1024)} KB"
    return f"{num_bytes / (1024 * 1024):.1f} MB"


def _prune_backups():
    archives = sorted(BACKUP_DIR.glob("*.tar.gz"), key=lambda p: p.name, reverse=True)
    for old in archives[MAX_BACKUPS:]:
        backup_id = old.name.replace(".tar.gz", "")
        old.unlink(missing_ok=True)
        _backup_meta_path(backup_id).unlink(missing_ok=True)


def _discord(event, **kwargs):
    try:
        from app.discord_manager import notify
        notify(event, **kwargs)
    except Exception:
        pass


def create_backup(version):
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup_id = _now_id()
    archive_path = _backup_archive_path(backup_id)

    with tarfile.open(archive_path, "w:gz") as tar:
        for name in BACKUP_ITEMS:
            src = MINECRAFT_DIR / name
            if src.exists():
                tar.add(src, arcname=name)

    size = archive_path.stat().st_size
    created = datetime.now()
    meta = {
        "id": backup_id,
        "version": version,
        "created": created.isoformat(),
        "created_label": created.strftime("%Y-%m-%d %H:%M"),
        "size": size,
        "size_label": _format_size(size),
    }
    _write_json(_backup_meta_path(backup_id), meta)
    _prune_backups()
    _discord("backup_success", size=meta.get("size_label", "-"))
    return backup_id, meta


def list_backups():
    backups = []
    for meta_path in sorted(BACKUP_DIR.glob("*.meta.json"), key=lambda p: p.name, reverse=True):
        meta = _read_json(meta_path, {})
        backup_id = meta.get("id") or meta_path.stem.replace(".meta", "")
        archive = _backup_archive_path(backup_id)
        if not archive.exists():
            continue
        if not meta.get("size"):
            size = archive.stat().st_size
            meta["size"] = size
            meta["size_label"] = _format_size(size)
        backups.append(meta)
    return backups[:MAX_BACKUPS]


def delete_backup(backup_id):
    if not re.fullmatch(r"\d{8}-\d{6}", backup_id):
        raise ValueError("Invalid backup id")
    _backup_archive_path(backup_id).unlink(missing_ok=True)
    _backup_meta_path(backup_id).unlink(missing_ok=True)


def restore_backup(backup_id):
    if not re.fullmatch(r"\d{8}-\d{6}", backup_id):
        raise ValueError("Invalid backup id")
    archive = _backup_archive_path(backup_id)
    if not archive.exists():
        raise FileNotFoundError("Backup archive not found")

    ok, msg = _systemctl("stop")
    if not ok:
        raise RuntimeError(f"Failed to stop bedrock: {msg}")

    with tarfile.open(archive, "r:gz") as tar:
        tar.extractall(path=MINECRAFT_DIR)

    ok, msg = _systemctl("start")
    if not ok:
        raise RuntimeError(f"Failed to start bedrock after restore: {msg}")

    if not wait_for_running():
        raise RuntimeError("Bedrock did not return to running state after restore")

    meta = _read_json(_backup_meta_path(backup_id), {})
    if meta.get("version"):
        save_installed_version(meta["version"])
    return True


def get_update_history():
    data = _read_json(HISTORY_FILE, {"entries": []})
    return data.get("entries", [])[:20]


def append_history(old_version, new_version, success):
    data = _read_json(HISTORY_FILE, {"entries": []})
    entries = data.get("entries", [])
    entries.insert(
        0,
        {
            "date": datetime.now().strftime("%Y/%m/%d"),
            "from_version": old_version,
            "to_version": new_version,
            "success": success,
            "status_label": "成功" if success else "失敗",
        },
    )
    _write_json(HISTORY_FILE, {"entries": entries[:20]})


def wait_for_running():
    for _ in range(POLL_START_ATTEMPTS):
        code, out, _ = _run(["systemctl", "is-active", "bedrock"], timeout=10)
        if code == 0 and out == "active":
            time.sleep(POLL_START_SECONDS)
            code, out, _ = _run(["systemctl", "is-active", "bedrock"], timeout=10)
            if code == 0 and out == "active":
                return True
        time.sleep(POLL_START_SECONDS)
    return False


def _download_latest(url, dest_path):
    req = urllib.request.Request(url, headers={"User-Agent": "MyCraftServer/1.0"})
    with urllib.request.urlopen(req, timeout=600) as resp, open(dest_path, "wb") as out:
        shutil.copyfileobj(resp, out)


def _extract_zip(zip_path, dest_dir):
    if dest_dir.exists():
        shutil.rmtree(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    code, _, err = _run(["unzip", "-oq", str(zip_path), "-d", str(dest_dir)], timeout=600)
    if code != 0:
        raise RuntimeError(f"Failed to extract update package: {err}")


def _apply_package(staging_dir):
    for item in staging_dir.iterdir():
        if item.name in PRESERVE_NAMES:
            continue
        dest = MINECRAFT_DIR / item.name
        if item.is_dir():
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(item, dest)
        else:
            shutil.copy2(item, dest)
    server_bin = MINECRAFT_DIR / "bedrock_server"
    if server_bin.exists():
        server_bin.chmod(0o775)


def _perform_update(download_url, latest_version, old_version):
    backup_id = None
    try:
        _discord("update_start", version=latest_version)
        _set_status("running", "backup", "バックアップを作成しています…")
        backup_id, _ = create_backup(old_version)

        _set_status("running", "stop", "サーバーを停止しています…")
        ok, msg = _systemctl("stop")
        if not ok:
            raise RuntimeError(f"Failed to stop bedrock: {msg}")

        WORK_DIR.mkdir(parents=True, exist_ok=True)
        zip_path = WORK_DIR / "bedrock-update.zip"
        staging_dir = WORK_DIR / "bedrock-staging"

        _set_status("running", "download", "最新版をダウンロードしています…")
        _download_latest(download_url, zip_path)

        _set_status("running", "install", "サーバーを更新しています…")
        _extract_zip(zip_path, staging_dir)
        _apply_package(staging_dir)

        _set_status("running", "start", "サーバーを起動しています…")
        ok, msg = _systemctl("start")
        if not ok:
            raise RuntimeError(f"Failed to start bedrock: {msg}")

        if not wait_for_running():
            raise RuntimeError("Bedrock failed to reach running state")

        save_installed_version(latest_version)
        append_history(old_version, latest_version, True)
        _discord("update_complete", from_version=old_version, to_version=latest_version)
        _set_status(
            "done",
            "done",
            "アップデートが完了しました",
            {"current_version": latest_version, "backup_id": backup_id},
        )
    except Exception as exc:
        _set_status("restoring", "restore", "バックアップから復元しています…", {"error": str(exc)})
        if backup_id:
            try:
                with tarfile.open(_backup_archive_path(backup_id), "r:gz") as tar:
                    tar.extractall(path=MINECRAFT_DIR)
            except Exception as restore_exc:
                _set_status(
                    "error",
                    "restore",
                    f"復元に失敗しました: {restore_exc}",
                    {"error": str(exc)},
                )
                append_history(old_version, latest_version, False)
                _discord("update_fail", detail=str(exc))
                return

        _systemctl("start")
        wait_for_running()
        append_history(old_version, latest_version, False)
        _discord("update_fail", detail=str(exc))
        _set_status(
            "error",
            "restore",
            "アップデートに失敗しました。バックアップから復元しました。",
            {"error": str(exc), "restored": True},
        )
    finally:
        zip_path = WORK_DIR / "bedrock-update.zip"
        staging_dir = WORK_DIR / "bedrock-staging"
        zip_path.unlink(missing_ok=True)
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)
        LOCK_FILE.unlink(missing_ok=True)


def start_update():
    if not _update_lock.acquire(blocking=False):
        return False, "Update already running"

    status = get_update_status()
    if status.get("state") in {"running", "restoring"}:
        _update_lock.release()
        return False, "Update already running"

    try:
        old_version = get_installed_version()
        latest, download_url = fetch_latest_release()
        if compare_versions(latest, old_version) <= 0:
            return False, "Already up to date"

        try:
            fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
        except FileExistsError:
            return False, "Update already running"

        _set_status("running", "backup", "アップデートを開始しています…")

        thread = threading.Thread(
            target=_perform_update,
            args=(download_url, latest, old_version),
            daemon=True,
        )
        thread.start()
        return True, "Update started"
    except Exception as exc:
        LOCK_FILE.unlink(missing_ok=True)
        return False, str(exc)
    finally:
        _update_lock.release()
