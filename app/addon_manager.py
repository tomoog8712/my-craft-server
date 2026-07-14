"""Global Minecraft Bedrock add-on manager (Ver2: auto-pairing, all worlds)."""

import json
import os
import re
import shutil
import subprocess
import threading
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from app.update_manager import compare_versions, get_installed_version, wait_for_running
from app.world_manager import (
    DEATH_NOTIFY_PACK_ID,
    WORLDS_DATA,
    WORLDS_DIR,
    _load_registry,
    _now_id,
    _now_iso,
    _read_json,
    _run,
    _stop_and_wait,
    _start_and_wait,
    _write_json,
    sync_registry,
)

LEGACY_ADDONS_ROOT = WORLDS_DATA / "addons"
ADDONS_ROOT = Path("/opt/appliance/data/addons")
WORK_DIR = Path("/opt/appliance/work")
ALLOWED_UPLOAD_EXT = {".mcpack", ".mcaddon", ".zip"}
BLOCKED_EXT = {
    ".exe", ".dll", ".sh", ".bat", ".cmd", ".msi", ".so", ".dylib",
    ".jar", ".com", ".scr", ".ps1", ".vbs", ".deb", ".rpm",
}
DEPLOY_SCRIPT = "/opt/appliance/bin/addon-deploy.sh"
REMOVE_SCRIPT = "/opt/appliance/bin/addon-remove.sh"
WORLD_JSON_SCRIPT = "/opt/appliance/bin/addon-world-json.sh"
MAX_ADDON_BACKUPS = 5
STARTUP_LOG_LINES = 250
VERIFY_STARTUP_TIMEOUT = 90
VERIFY_POLL_SECONDS = 2

_lock = threading.RLock()


def _addons_dir():
    return ADDONS_ROOT


def _registry_path():
    return ADDONS_ROOT / "registry.json"


def _history_path():
    return ADDONS_ROOT / "history.json"


def _backup_dir():
    return ADDONS_ROOT / "backups"


def _packs_dir():
    return ADDONS_ROOT / "packs"


def _migrate_legacy_if_needed():
    ADDONS_ROOT.mkdir(parents=True, exist_ok=True)
    if _registry_path().exists():
        return
    if not LEGACY_ADDONS_ROOT.is_dir():
        return
    candidates = []
    for d in LEGACY_ADDONS_ROOT.iterdir():
        rp = d / "registry.json"
        if rp.is_file():
            data = _read_json(rp, {})
            candidates.append((data.get("updated_at") or "", d))
    if not candidates:
        return
    candidates.sort(reverse=True)
    legacy = candidates[0][1]
    for name in ("registry.json", "history.json"):
        srcf = legacy / name
        if srcf.is_file():
            shutil.copy2(srcf, ADDONS_ROOT / name)
    if (legacy / "packs").is_dir():
        shutil.copytree(legacy / "packs", ADDONS_ROOT / "packs", dirs_exist_ok=True)
    if (legacy / "backups").is_dir():
        shutil.copytree(legacy / "backups", ADDONS_ROOT / "backups", dirs_exist_ok=True)
    reg = _read_json(_registry_path(), _default_registry())
    legacy_prefix = str(legacy)
    global_prefix = str(ADDONS_ROOT)
    for pack in reg.get("packs", []):
        for kind in ("behavior", "resource"):
            slot = pack.get(kind) or {}
            lp = slot.get("local_path") or ""
            if lp.startswith(legacy_prefix):
                slot["local_path"] = lp.replace(legacy_prefix, global_prefix, 1)
    _write_json(_registry_path(), reg)


def _ensure_initialized():
    _migrate_legacy_if_needed()
    ADDONS_ROOT.mkdir(parents=True, exist_ok=True)


def _all_world_entries():
    reg = sync_registry()
    return list(reg.get("worlds", {}).items())


def _active_world_id():
    reg = sync_registry()
    return reg.get("active_id") or ""


def _is_server_active():
    return bool(_active_world_id())


def _default_registry():
    return {
        "packs": [],
        "last_backup_id": "",
        "rollback_available": False,
        "updated_at": _now_iso(),
    }


def _default_history():
    return {"entries": []}


def _load_registry_data():
    _ensure_initialized()
    return _read_json(_registry_path(), _default_registry())


def _save_registry_data(data):
    data["updated_at"] = _now_iso()
    _write_json(_registry_path(), data)


def _load_history():
    return _read_json(_history_path(), _default_history())


def _save_history(data):
    _write_json(_history_path(), data)


def _append_history(pack_name, action):
    hist = _load_history()
    now = datetime.now()
    hist.setdefault("entries", []).insert(0, {
        "at": _now_iso(),
        "at_label": now.strftime("%Y/%m/%d"),
        "pack_name": pack_name,
        "action": action,
    })
    hist["entries"] = hist["entries"][:100]
    _save_history(hist)


def _world_entry(world_id):
    reg = sync_registry()
    if world_id not in reg.get("worlds", {}):
        raise ValueError("ワールドが見つかりません")
    return reg["worlds"][world_id]


def _world_path(world_id):
    entry = _world_entry(world_id)
    path = WORLDS_DIR / entry["folder"]
    if not path.is_dir():
        raise ValueError("ワールドフォルダが見つかりません")
    return path, entry


def _version_label(version):
    if not version:
        return "情報なし"
    if isinstance(version, list):
        parts = [str(x) for x in version[:4]]
        return ".".join(parts) if parts else "情報なし"
    return str(version)


def _version_tuple_str(parts):
    if not parts:
        return ""
    return ".".join(str(x) for x in parts[:4])


def _parse_manifest(path):
    info = {
        "name": "情報なし",
        "uuid": "",
        "version": [],
        "version_label": "情報なし",
        "min_engine_version": [],
        "min_engine_label": "情報なし",
        "author": "情報なし",
        "description": "情報なし",
        "pack_kind": "unknown",
        "dependencies": [],
        "behavior_uuid": "",
        "resource_uuid": "",
        "path": str(path),
    }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return info

    header = data.get("header") or {}
    info["name"] = header.get("name") or "情報なし"
    info["uuid"] = (header.get("uuid") or "").lower()
    info["version"] = header.get("version") or []
    info["version_label"] = _version_label(info["version"])
    info["min_engine_version"] = header.get("min_engine_version") or []
    info["min_engine_label"] = _version_tuple_str(info["min_engine_version"]) or "情報なし"
    info["description"] = header.get("description") or "情報なし"
    info["dependencies"] = data.get("dependencies") or []

    metadata = data.get("metadata") or {}
    authors = metadata.get("authors") or header.get("authors") or []
    if isinstance(authors, list) and authors:
        first = authors[0]
        if isinstance(first, dict):
            info["author"] = first.get("name") or "情報なし"
        else:
            info["author"] = str(first)
    elif isinstance(authors, str) and authors:
        info["author"] = authors

    kinds = set()
    for module in data.get("modules") or []:
        mtype = (module.get("type") or "").lower()
        muuid = (module.get("uuid") or "").lower()
        if mtype in ("data", "script"):
            kinds.add("behavior")
            info["behavior_uuid"] = info["behavior_uuid"] or muuid or info["uuid"]
        elif mtype in ("resources", "resource", "skin_pack"):
            kinds.add("resource")
            info["resource_uuid"] = info["resource_uuid"] or muuid or info["uuid"]
    if kinds:
        info["pack_kind"] = "both" if len(kinds) > 1 else next(iter(kinds))
    if not info["behavior_uuid"] and info["pack_kind"] in ("behavior", "both"):
        info["behavior_uuid"] = info["uuid"]
    if not info["resource_uuid"] and info["pack_kind"] in ("resource", "both"):
        info["resource_uuid"] = info["uuid"]
    return info


def _normalize_addon_name(name):
    n = (name or "").strip().lower()
    for token in (
        " behavior pack", " resource pack", " behavior", " resource",
        " bp", " rp", " pack",
    ):
        if n.endswith(token):
            n = n[: -len(token)]
    n = re.sub(r"[^a-z0-9\u3040-\u30ff\u4e00-\u9fff]+", " ", n)
    return n.strip()


def _filename_stem_hint(filename):
    stem = Path(filename or "").stem.lower()
    for suffix in ("behavior", "resource", "behaviour", "pack", "addon"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
    return stem.strip("_- ")


def _slot_uuid(pack, kind):
    slot = pack.get(kind) or {}
    if kind == "resource":
        return (slot.get("pack_id") or "").lower()
    return (pack.get("pack_id") or "").lower()


def _pack_has_slot(pack, kind):
    slot = pack.get(kind) or {}
    return bool(slot.get("folder") or slot.get("local_path"))


def _is_installable(pack):
    return _pack_has_slot(pack, "behavior") and _pack_has_slot(pack, "resource")


def _pack_enabled(pack):
    return bool((pack.get("behavior") or {}).get("enabled")) or bool((pack.get("resource") or {}).get("enabled"))


def _find_pairing_target(packs, manifest, source_name):
    norm = _normalize_addon_name(manifest["name"])
    stem = _filename_stem_hint(source_name)
    manifest_uuid = (manifest.get("uuid") or "").lower()
    kind = manifest.get("pack_kind") or "unknown"
    dep_uuids = {
        (dep.get("uuid") or "").lower()
        for dep in (manifest.get("dependencies") or [])
        if isinstance(dep, dict)
    }

    best = None
    best_score = 0
    for pack in packs:
        score = 0
        pack_norm = _normalize_addon_name(pack.get("name"))
        pack_stem = pack.get("pair_hint") or ""

        for dep_uuid in dep_uuids:
            if dep_uuid and dep_uuid in {
                (pack.get("pack_id") or "").lower(),
                _slot_uuid(pack, "behavior"),
                _slot_uuid(pack, "resource"),
            }:
                score = max(score, 100)

        if norm and pack_norm and norm == pack_norm:
            score = max(score, 80)
        if stem and pack_stem and stem == pack_stem:
            score = max(score, 70)

        if kind == "behavior" and _pack_has_slot(pack, "resource") and not _pack_has_slot(pack, "behavior"):
            if norm and pack_norm and norm == pack_norm:
                score = max(score, 90)
            if stem and pack_stem and stem == pack_stem:
                score = max(score, 85)
        if kind == "resource" and _pack_has_slot(pack, "behavior") and not _pack_has_slot(pack, "resource"):
            if norm and pack_norm and norm == pack_norm:
                score = max(score, 90)
            if stem and pack_stem and stem == pack_stem:
                score = max(score, 85)

        if manifest_uuid and manifest_uuid in {
            (pack.get("pack_id") or "").lower(),
            _slot_uuid(pack, "behavior"),
            _slot_uuid(pack, "resource"),
        }:
            score = max(score, 95)

        if score > best_score:
            best = pack
            best_score = score

    return best if best_score >= 70 else None


def _check_compatibility(min_engine_version):
    installed = get_installed_version()
    if not min_engine_version or not installed or installed == "unknown":
        return True, ""
    required = _version_tuple_str(min_engine_version)
    if not required:
        return True, ""
    if compare_versions(installed, required) < 0:
        return False, f"Minecraft {installed} / Add-on {required}"
    return True, ""


def _validate_upload_name(name):
    lower = (name or "").lower()
    ext = Path(lower).suffix
    if ext not in ALLOWED_UPLOAD_EXT:
        raise ValueError("対応形式は .mcpack / .mcaddon / .zip のみです")


def _is_safe_member(name):
    norm = name.replace("\\", "/")
    if norm.startswith("/") or ".." in norm.split("/"):
        return False
    parts = norm.split("/")
    for part in parts:
        if not part or part in (".", ".."):
            continue
        ext = Path(part).suffix.lower()
        if ext in BLOCKED_EXT:
            return False
    return True


def _extract_upload(upload_path, dest_dir):
    dest_dir.mkdir(parents=True, exist_ok=True)
    lower = upload_path.name.lower()
    if lower.endswith(".mcpack") or lower.endswith(".mcaddon") or lower.endswith(".zip"):
        with zipfile.ZipFile(upload_path, "r") as zf:
            for member in zf.infolist():
                if member.is_dir():
                    continue
                if not _is_safe_member(member.filename):
                    raise ValueError("安全でないファイルが含まれています")
                ext = Path(member.filename).suffix.lower()
                if ext in BLOCKED_EXT:
                    raise ValueError(f"許可されていないファイルです: {ext}")
            zf.extractall(dest_dir)
        return
    raise ValueError("対応形式は .mcpack / .mcaddon / .zip のみです")


def _find_manifest_dirs(root):
    found = []
    for path in sorted(root.rglob("manifest.json")):
        if not _is_safe_member(str(path.relative_to(root))):
            continue
        found.append(path.parent)
    return found


def _server_folder_name(pack_id):
    short = re.sub(r"[^a-f0-9]", "", (pack_id or "unknown").lower())[:8] or "unknown"
    return f"a_{short}"


def _sudo_deploy(src_dir, kind, folder_name):
    code, out, err = _run(
        ["sudo", "-n", DEPLOY_SCRIPT, str(src_dir), kind, folder_name],
        timeout=120,
    )
    if code != 0 or out != "OK":
        raise RuntimeError(err or out or "アドオンの配置に失敗しました")


def _sudo_remove(kind, folder_name):
    if not folder_name:
        return
    _run(["sudo", "-n", REMOVE_SCRIPT, kind, folder_name], timeout=60)


def _write_world_json(world_path, kind, entries):
    tmp = WORK_DIR / f"addon-json-{_now_id()}.json"
    tmp.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    code, out, err = _run(
        ["sudo", "-n", WORLD_JSON_SCRIPT, str(world_path), kind, str(tmp)],
        timeout=30,
    )
    tmp.unlink(missing_ok=True)
    if code != 0 or out != "OK":
        raise RuntimeError(err or out or "ワールド設定の更新に失敗しました")


def _build_world_pack_lists(registry):
    behavior = []
    resource = []
    for pack in registry.get("packs", []):
        if not _is_installable(pack):
            continue
        if pack.get("behavior", {}).get("enabled"):
            behavior.append({
                "pack_id": pack["pack_id"],
                "version": pack.get("version") or [1, 0, 0],
            })
        res = pack.get("resource") or {}
        if res.get("enabled") and res.get("pack_id"):
            resource.append({
                "pack_id": res["pack_id"],
                "version": res.get("version") or pack.get("version") or [1, 0, 0],
            })
    return behavior, resource


def _ensure_death_notify(behavior_entries):
    entry = {"pack_id": DEATH_NOTIFY_PACK_ID, "version": [1, 0, 0]}
    if not any(p.get("pack_id") == DEATH_NOTIFY_PACK_ID for p in behavior_entries):
        behavior_entries.append(entry)
    return behavior_entries


def _sync_world_pack_files(world_id, registry):
    world_path, _entry = _world_path(world_id)
    behavior, resource = _build_world_pack_lists(registry)
    behavior = _ensure_death_notify(behavior)
    _write_world_json(world_path, "behavior", behavior)
    if resource:
        _write_world_json(world_path, "resource", resource)
    elif (world_path / "world_resource_packs.json").exists():
        _write_world_json(world_path, "resource", [])


def _sync_all_world_pack_files(registry):
    for world_id, _entry in _all_world_entries():
        try:
            _sync_world_pack_files(world_id, registry)
        except ValueError:
            continue


def _create_addon_backup():
    backup_id = _now_id()
    dest = _backup_dir() / backup_id
    dest.mkdir(parents=True, exist_ok=True)

    packs_root = _packs_dir()
    if packs_root.exists():
        shutil.copytree(packs_root, dest / "packs", dirs_exist_ok=True)

    reg = _load_registry_data()
    _write_json(dest / "registry.json", reg)

    worlds_dest = dest / "worlds"
    for world_id, entry in _all_world_entries():
        world_path = WORLDS_DIR / entry["folder"]
        if not world_path.is_dir():
            continue
        wdest = worlds_dest / world_id
        wdest.mkdir(parents=True, exist_ok=True)
        for filename in ("world_behavior_packs.json", "world_resource_packs.json"):
            srcf = world_path / filename
            if srcf.exists():
                shutil.copy2(srcf, wdest / filename)

    meta = {
        "id": backup_id,
        "type": "AddonBackup",
        "scope": "global",
        "created": _now_iso(),
        "created_label": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    _write_json(dest / "meta.json", meta)

    reg_data = _load_registry_data()
    reg_data["last_backup_id"] = backup_id
    reg_data["rollback_available"] = True
    _save_registry_data(reg_data)

    backups = sorted(_backup_dir().iterdir(), key=lambda p: p.name, reverse=True)
    for old in backups[MAX_ADDON_BACKUPS:]:
        if old.is_dir():
            shutil.rmtree(old, ignore_errors=True)
    return backup_id, meta


def _restore_addon_backup(backup_id=None):
    reg = _load_registry_data()
    backup_id = backup_id or reg.get("last_backup_id")
    if not backup_id:
        raise ValueError("復元できるバックアップがありません")

    src = _backup_dir() / backup_id
    if not src.is_dir():
        raise FileNotFoundError("バックアップが見つかりません")

    current = _load_registry_data()

    for pack in current.get("packs", []):
        for kind in ("behavior", "resource"):
            slot = pack.get(kind) or {}
            folder = slot.get("folder")
            if folder:
                _sudo_remove(kind, folder)

    packs_src = src / "packs"
    packs_dest = _packs_dir()
    if packs_dest.exists():
        shutil.rmtree(packs_dest)
    if packs_src.exists():
        shutil.copytree(packs_src, packs_dest)

    restored = _read_json(src / "registry.json", _default_registry())
    _save_registry_data(restored)

    for pack in restored.get("packs", []):
        for kind in ("behavior", "resource"):
            slot = pack.get(kind) or {}
            folder = slot.get("folder")
            local = slot.get("local_path")
            if folder and local:
                local_path = Path(local)
                if local_path.exists():
                    _sudo_deploy(local_path, kind, folder)

    worlds_src = src / "worlds"
    if worlds_src.is_dir():
        for world_id, entry in _all_world_entries():
            wsrc = worlds_src / world_id
            if not wsrc.is_dir():
                continue
            world_path = WORLDS_DIR / entry["folder"]
            for kind, filename in (
                ("behavior", "world_behavior_packs.json"),
                ("resource", "world_resource_packs.json"),
            ):
                backup_json = wsrc / filename
                if backup_json.exists():
                    entries = _read_json(backup_json, [])
                    _write_world_json(world_path, kind, entries if isinstance(entries, list) else [])
    else:
        _sync_all_world_pack_files(restored)

    return True, "アドオン設定を元に戻しました"


def _bedrock_logs_since(since):
    code, out, _ = _run(
        ["journalctl", "-u", "bedrock", f"--since={since}", "--no-pager", "-o", "cat"],
        timeout=20,
    )
    return out or ""


def _scan_bedrock_errors(logs):
    crash_markers = (
        "failed to load behavior pack",
        "failed to load resource pack",
        "error loading pack",
        "pack stack error",
        "json parse error",
        "failed to parse",
        "fatal error",
        "failed to open world",
        "couldn't load level",
        "leveldb corruption",
    )
    errors = []
    for line in logs.splitlines():
        ll = line.lower()
        if any(marker in ll for marker in crash_markers):
            errors.append(line.strip())
    return errors


def _verify_bedrock_startup(since):
    """Wait for Bedrock to finish booting and inspect only logs from this restart."""
    deadline = time.time() + VERIFY_STARTUP_TIMEOUT
    last_logs = ""

    while time.time() < deadline:
        if not wait_for_running():
            time.sleep(VERIFY_POLL_SECONDS)
            continue

        last_logs = _bedrock_logs_since(since)
        lowered = last_logs.lower()
        errors = _scan_bedrock_errors(last_logs)
        if errors:
            return False, errors[:5]

        if "server started" in lowered:
            return True, []

        time.sleep(VERIFY_POLL_SECONDS)

    if last_logs.strip():
        errors = _scan_bedrock_errors(last_logs)
        if errors:
            return False, errors[:5]
        if "opening level" in last_logs.lower() or "pack stack" in last_logs.lower():
            return False, ["サーバーの起動完了（Server started）を確認できませんでした"]
    return False, ["サーバーの起動確認がタイムアウトしました"]


def _restart_and_verify_or_rollback(backup_id):
    active = _is_server_active()
    if not active:
        return True, {
            "startup_ok": True,
            "needs_restart": False,
            "apply_result": "success",
            "message": "設定を保存しました",
        }

    since = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _stop_and_wait()
    try:
        _start_and_wait()
    except RuntimeError as exc:
        _restore_addon_backup(backup_id)
        _stop_and_wait()
        _start_and_wait()
        return False, {
            "startup_ok": False,
            "rolled_back": True,
            "apply_result": "failed",
            "needs_restart": False,
            "verification_errors": [str(exc)],
            "message": "正常に起動できなかったため変更を元へ戻しました。ワールドは保護されています。",
        }

    ok, errors = _verify_bedrock_startup(since)
    if not ok:
        _restore_addon_backup(backup_id)
        _stop_and_wait()
        _start_and_wait()
        return False, {
            "startup_ok": False,
            "rolled_back": True,
            "apply_result": "failed",
            "needs_restart": False,
            "verification_errors": errors,
            "message": "正常に起動できなかったため変更を元へ戻しました。ワールドは保護されています。",
        }

    return True, {
        "startup_ok": True,
        "apply_result": "success",
        "needs_restart": False,
        "restarted": True,
        "message": "アドオンを適用しました。サーバーは正常に起動しています。実際の動作はゲーム内で確認してください。",
    }


def _deploy_slot(pack_dir, kind, pack_uuid):
    packs_dir = _packs_dir()
    server_folder = _server_folder_name(pack_uuid)
    local_kind_dir = packs_dir / kind / server_folder
    if local_kind_dir.exists():
        shutil.rmtree(local_kind_dir)
    shutil.copytree(pack_dir, local_kind_dir)
    _sudo_deploy(local_kind_dir, kind, server_folder)
    return server_folder, str(local_kind_dir)


def _remove_slot(slot, kind):
    folder = (slot or {}).get("folder")
    local_path = (slot or {}).get("local_path")
    if folder:
        _sudo_remove(kind, folder)
    if local_path:
        lp = Path(local_path)
        if lp.exists():
            shutil.rmtree(lp, ignore_errors=True)


def _merge_manifest_into_pack(pack, manifest, pack_dir, source_name, enabled_default=False):
    kind = manifest.get("pack_kind") or "unknown"
    if kind == "unknown":
        kind = "behavior"

    if kind == "both":
        behavior_uuid = manifest.get("behavior_uuid") or manifest.get("uuid")
        resource_uuid = manifest.get("resource_uuid") or manifest.get("uuid")
        b_folder, b_local = _deploy_slot(pack_dir, "behavior", behavior_uuid)
        r_folder, r_local = _deploy_slot(pack_dir, "resource", resource_uuid)
        enabled = enabled_default or _pack_enabled(pack)
        pack["pack_id"] = behavior_uuid
        pack["behavior"] = {
            "folder": b_folder,
            "local_path": b_local,
            "enabled": enabled,
        }
        pack["resource"] = {
            "pack_id": resource_uuid,
            "folder": r_folder,
            "local_path": r_local,
            "version": manifest.get("version") or [1, 0, 0],
            "enabled": enabled,
        }
        return

    pack_uuid = manifest.get("uuid")
    if not pack_uuid:
        return

    if kind == "behavior":
        folder, local = _deploy_slot(pack_dir, "behavior", pack_uuid)
        enabled = enabled_default or bool((pack.get("behavior") or {}).get("enabled"))
        if not pack.get("pack_id"):
            pack["pack_id"] = pack_uuid
        pack["behavior"] = {
            "folder": folder,
            "local_path": local,
            "enabled": enabled,
        }
    elif kind == "resource":
        folder, local = _deploy_slot(pack_dir, "resource", pack_uuid)
        enabled = enabled_default or bool((pack.get("resource") or {}).get("enabled"))
        pack["resource"] = {
            "pack_id": pack_uuid,
            "folder": folder,
            "local_path": local,
            "version": manifest.get("version") or [1, 0, 0],
            "enabled": enabled,
        }
        if not pack.get("pack_id"):
            pack["pack_id"] = pack_uuid


def _ingest_manifest(registry, pack_dir, manifest, source_name):
    packs = registry.setdefault("packs", [])
    was_installable = False
    target = _find_pairing_target(packs, manifest, source_name)

    if target:
        was_installable = _is_installable(target)
        _merge_manifest_into_pack(target, manifest, pack_dir, source_name)
        target["name"] = target.get("name") or manifest.get("name")
        target["version"] = manifest.get("version") or target.get("version") or []
        target["version_label"] = manifest.get("version_label") or target.get("version_label")
        target["author"] = manifest.get("author") or target.get("author")
        target["description"] = manifest.get("description") or target.get("description")
        target["min_engine_version"] = manifest.get("min_engine_version") or target.get("min_engine_version")
        target["min_engine_label"] = manifest.get("min_engine_label") or target.get("min_engine_label")
        target["pair_hint"] = target.get("pair_hint") or _filename_stem_hint(source_name)
        pack_entry = target
    else:
        pack_entry = {
            "pack_id": manifest.get("behavior_uuid") or manifest.get("uuid"),
            "name": manifest.get("name"),
            "version": manifest.get("version") or [],
            "version_label": manifest.get("version_label"),
            "author": manifest.get("author"),
            "description": manifest.get("description"),
            "min_engine_version": manifest.get("min_engine_version") or [],
            "min_engine_label": manifest.get("min_engine_label"),
            "installed_at": _now_iso(),
            "pair_hint": _filename_stem_hint(source_name),
        }
        _merge_manifest_into_pack(pack_entry, manifest, pack_dir, source_name, enabled_default=False)
        packs.append(pack_entry)

    now_installable = _is_installable(pack_entry)
    if now_installable and not was_installable:
        _append_history(pack_entry.get("name") or "アドオン", "インストール")
    return pack_entry


def _public_pack(pack):
    installable = _is_installable(pack)
    enabled = _pack_enabled(pack)
    if not installable:
        status = "incomplete"
        status_label = "追加ファイルが必要です"
        state_class = "incomplete"
        state_icon = "🟡"
    elif enabled:
        status = "enabled"
        status_label = "有効"
        state_class = "on"
        state_icon = "🟢"
    else:
        status = "installable"
        status_label = "インストール可能"
        state_class = "ready"
        state_icon = "🟢"

    return {
        "pack_id": pack.get("pack_id"),
        "name": pack.get("name") or "情報なし",
        "version_label": pack.get("version_label") or "情報なし",
        "author": pack.get("author") or "情報なし",
        "description": pack.get("description") or "情報なし",
        "min_engine_label": pack.get("min_engine_label") or "情報なし",
        "enabled": enabled,
        "installable": installable,
        "status": status,
        "status_label": status_label,
        "state_class": state_class,
        "state_icon": state_icon,
        "can_enable": installable and not enabled,
        "can_disable": installable and enabled,
        "installed_at": pack.get("installed_at") or "",
    }


def get_addon_state():
    _ensure_initialized()
    reg = _load_registry_data()
    hist = _load_history()
    installed = get_installed_version()
    world_count = len(_all_world_entries())
    return {
        "scope": "global",
        "world_count": world_count,
        "active": _is_server_active(),
        "minecraft_version": installed,
        "addons": [_public_pack(p) for p in reg.get("packs", [])],
        "history": hist.get("entries", [])[:20],
        "rollback_available": bool(reg.get("rollback_available")),
        "last_backup_id": reg.get("last_backup_id") or "",
    }


def sync_addons_to_all_worlds():
    """Apply current global addon registry to every world JSON."""
    _ensure_initialized()
    reg = _load_registry_data()
    _sync_all_world_pack_files(reg)
    return True


def analyze_addon_upload(upload_path, original_name):
    _validate_upload_name(original_name)
    upload = Path(upload_path)
    if not upload.is_file():
        raise ValueError("ファイルが見つかりません")

    tmp = WORK_DIR / f"addon-analyze-{_now_id()}"
    tmp.mkdir(parents=True, exist_ok=True)
    try:
        _extract_upload(upload, tmp)
        manifests = _find_manifest_dirs(tmp)
        if not manifests:
            raise ValueError("manifest.json が見つかりません")

        previews = []
        warnings = []
        for pack_dir in manifests:
            manifest = _parse_manifest(pack_dir / "manifest.json")
            if not manifest["uuid"]:
                continue
            compatible, detail = _check_compatibility(manifest["min_engine_version"])
            item = {
                "name": manifest["name"],
                "uuid": manifest["uuid"],
                "version_label": manifest["version_label"],
                "author": manifest["author"],
                "description": manifest["description"],
                "min_engine_label": manifest["min_engine_label"],
                "pack_kind": manifest["pack_kind"],
                "compatible": compatible,
            }
            previews.append(item)
            if not compatible:
                warnings.append({
                    "name": manifest["name"],
                    "detail": detail,
                })
        if not previews:
            raise ValueError("有効なアドオン情報を読み取れませんでした")
        return {
            "previews": previews,
            "warnings": warnings,
            "needs_confirm": bool(warnings),
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _ingest_upload_file(upload_path, original_name):
    upload = Path(upload_path)
    tmp = WORK_DIR / f"addon-upload-{_now_id()}"
    tmp.mkdir(parents=True, exist_ok=True)
    added = []
    try:
        _extract_upload(upload, tmp)
        manifests = _find_manifest_dirs(tmp)
        if not manifests:
            raise ValueError(f"{original_name}: manifest.json が見つかりません")

        reg = _load_registry_data()
        for pack_dir in manifests:
            manifest = _parse_manifest(pack_dir / "manifest.json")
            if not manifest.get("uuid") and not manifest.get("behavior_uuid") and not manifest.get("resource_uuid"):
                continue
            entry = _ingest_manifest(reg, pack_dir, manifest, original_name)
            added.append(entry.get("name") or original_name)
        _save_registry_data(reg)
        return added
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def upload_addons(file_items, force=False):
    with _lock:
        if not file_items:
            raise ValueError("ファイルを選択してください")

        all_warnings = []
        all_previews = []
        for path, name in file_items:
            _validate_upload_name(name)
            analysis = analyze_addon_upload(path, name)
            all_previews.extend(analysis.get("previews") or [])
            all_warnings.extend(analysis.get("warnings") or [])

        if all_warnings and not force:
            return False, {
                "needs_confirm": True,
                "warnings": all_warnings,
                "previews": all_previews,
            }

        added_names = []
        for path, name in file_items:
            added_names.extend(_ingest_upload_file(path, name))

        unique = []
        seen = set()
        for n in added_names:
            if n not in seen:
                unique.append(n)
                seen.add(n)

        msg = "ファイルを追加しました"
        if len(file_items) > 1:
            msg = f"{len(file_items)}件のファイルを追加しました"
        if unique:
            msg = msg + "（" + "、".join(unique[:3]) + (" 他" if len(unique) > 3 else "") + "）"

        return True, {
            "message": msg,
            "added": unique,
            "needs_restart": False,
            "apply_result": "uploaded",
        }


def install_addon(upload_path, original_name, force=False, restart=False):
    ok, result = upload_addons([(upload_path, original_name)], force=force)
    return ok, result


def set_addon_enabled(pack_id, enabled, restart=False):
    with _lock:
        active = _is_server_active()
        reg = _load_registry_data()
        pack = next((p for p in reg.get("packs", []) if p.get("pack_id") == pack_id), None)
        if not pack:
            raise ValueError("アドオンが見つかりません")

        if enabled and not _is_installable(pack):
            raise ValueError("追加ファイルが必要です。このアドオンには不足しているパックがあります。")

        backup_id, _meta = _create_addon_backup()
        for kind in ("behavior", "resource"):
            slot = pack.get(kind)
            if slot:
                slot["enabled"] = bool(enabled)
        _save_registry_data(reg)
        _sync_all_world_pack_files(reg)
        _append_history(pack.get("name") or pack_id, "ON" if enabled else "OFF")

        if restart and active:
            ok, verify = _restart_and_verify_or_rollback(backup_id)
            if not ok:
                return False, verify
            return True, verify

        return True, {
            "message": "アドオンを有効にしました" if enabled else "アドオンを無効にしました",
            "needs_restart": active and not restart,
            "restarted": False,
            "apply_result": "pending_restart",
        }


def delete_addon(pack_id, restart=False):
    with _lock:
        active = _is_server_active()
        reg = _load_registry_data()
        packs = reg.get("packs", [])
        pack = next((p for p in packs if p.get("pack_id") == pack_id), None)
        if not pack:
            raise ValueError("アドオンが見つかりません")

        backup_id, _meta = _create_addon_backup()
        name = pack.get("name") or pack_id

        for kind in ("behavior", "resource"):
            _remove_slot(pack.get(kind), kind)

        reg["packs"] = [p for p in packs if p.get("pack_id") != pack_id]
        _save_registry_data(reg)
        _sync_all_world_pack_files(reg)
        _append_history(name, "削除")

        if restart and active:
            ok, verify = _restart_and_verify_or_rollback(backup_id)
            if not ok:
                return False, verify
            return True, verify

        return True, {
            "message": "アドオンを削除しました",
            "needs_restart": active and not restart,
            "restarted": False,
            "apply_result": "pending_restart",
        }


def rollback_addons(restart=False):
    with _lock:
        active = _is_server_active()
        ok, msg = _restore_addon_backup()
        if restart and active:
            since = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            _stop_and_wait()
            _start_and_wait()
            startup_ok, _errors = _verify_bedrock_startup(since)
            return ok, {
                "message": msg,
                "needs_restart": False,
                "restarted": True,
                "startup_ok": startup_ok,
                "apply_result": "success" if startup_ok else "failed",
            }
        return ok, {
            "message": msg,
            "needs_restart": active and not restart,
            "restarted": False,
            "apply_result": "pending_restart",
        }


def restart_server_for_addons():
    reg = _load_registry_data()
    backup_id = reg.get("last_backup_id")
    if _is_server_active() and backup_id:
        ok, result = _restart_and_verify_or_rollback(backup_id)
        if not ok:
            return False, result if isinstance(result, dict) else {"message": str(result)}
        return True, result if isinstance(result, dict) else {"message": str(result)}
    since = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _stop_and_wait()
    _start_and_wait()
    startup_ok, _errors = _verify_bedrock_startup(since)
    if not startup_ok:
        return False, "サーバーの起動確認に失敗しました"
    return True, "サーバーを再起動しました"


def reset_all_addons(restart=True):
    """Remove all add-ons and reset registry, history, and backups."""
    with _lock:
        _ensure_initialized()
        active = _is_server_active()
        reg = _load_registry_data()

        for pack in reg.get("packs", []):
            for kind in ("behavior", "resource"):
                _remove_slot(pack.get(kind), kind)

        for sub in ("packs", "backups"):
            path = ADDONS_ROOT / sub
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)

        _packs_dir().mkdir(parents=True, exist_ok=True)
        _backup_dir().mkdir(parents=True, exist_ok=True)
        _save_registry_data(_default_registry())
        _save_history(_default_history())

        try:
            _sync_all_world_pack_files(_default_registry())
        except Exception:
            pass

        if restart and active:
            since = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            _stop_and_wait()
            _start_and_wait()
            startup_ok, errors = _verify_bedrock_startup(since)
            if not startup_ok:
                detail = errors[0] if errors else "サーバーの起動確認に失敗しました"
                raise RuntimeError(detail)
