"""Player management for My Craft Server (Bedrock-first, Java-ready)."""

import json
import re
import subprocess
import threading
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path

from app.settings_manager import write_properties

DATA_DIR = Path("/opt/appliance/data/players")
REGISTRY_FILE = DATA_DIR / "registry.json"
BANLIST_FILE = DATA_DIR / "banlist.json"
DELETED_FILE = DATA_DIR / "deleted.json"
CONFIG_FILE = DATA_DIR / "config.json"
MINECRAFT_DIR = Path("/opt/minecraft")
CONSOLE_FIFO = MINECRAFT_DIR / "console.fifo"

CONSOLE_SCRIPT = "/opt/appliance/bin/bedrock-console-send.sh"
JSON_WRITE_SCRIPT = "/opt/appliance/bin/bedrock-json-write.sh"

PERMISSION_LABELS = {
    "operator": "オペレーター",
    "member": "メンバー",
    "visitor": "ビジター",
}

JOIN_XUID_RE = re.compile(r"Player connected:\s*([^,]+),\s*xuid:\s*(\d+)")
JOIN_NAME_RE = re.compile(r"Player connected:\s*([^,]+)")

_lock = threading.Lock()


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _run(cmd, timeout=30):
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode, (result.stdout or "").strip(), (result.stderr or "").strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        return 1, "", str(exc)


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read_json(path, default=None):
    if default is None:
        default = {}
    try:
        raw = path.read_text(encoding="utf-8")
        return json.loads(raw) if raw.strip() else default
    except (OSError, json.JSONDecodeError):
        return default


def _safe_write_bedrock_json(kind, data):
    tmp = DATA_DIR / f"bedrock-{kind}-{_now_id()}.json"
    _write_json(tmp, data)
    code, out, err = _run(["sudo", "-n", JSON_WRITE_SCRIPT, kind, str(tmp)], timeout=30)
    tmp.unlink(missing_ok=True)
    if code != 0 or out != "OK":
        raise RuntimeError(err or out or f"{kind}.json の更新に失敗しました")
    return True


def _now_id():
    return datetime.now().strftime("%Y%m%d%H%M%S%f")


def _send_console(command):
    code, out, err = _run(["sudo", "-n", CONSOLE_SCRIPT, command], timeout=4)
    if code == 2 or "NOT_READY" in err:
        return False, "サーバーが起動していないか、コンソールが利用できません"
    if code != 0 or out != "OK":
        return False, err or out or "コンソールコマンドの送信に失敗しました"
    return True, ""


def _server_running():
    code, out, _ = _run(["systemctl", "is-active", "bedrock"], timeout=5)
    return code == 0 and out == "active"


def _bedrock_listening():
    code, out, _ = _run(["pgrep", "-x", "bedrock_server"], timeout=5)
    if code == 0 and out.strip():
        return True
    code, out, _ = _run(["ss", "-Hlnup", "sport", "=", ":19132"], timeout=5)
    return code == 0 and bool(out.strip())


def _console_ready():
    return _server_running() and CONSOLE_FIFO.exists() and _bedrock_listening()


def _restart_bedrock_and_wait(timeout_sec=90):
    code, _, err = _run(["sudo", "-n", "/usr/bin/systemctl", "restart", "bedrock"], timeout=60)
    if code != 0:
        raise RuntimeError(err or "サーバー再起動に失敗しました")
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        time.sleep(2)
        if _server_running() and CONSOLE_FIFO.exists() and _bedrock_listening():
            time.sleep(2)
            ok, _ = _send_console("list")
            if ok:
                return True
    raise RuntimeError("サーバーの起動を確認できませんでした")


def _ensure_console():
    """Try to obtain a console without restarting (restart only when explicitly requested)."""
    return _console_ready()


def _load_player_config():
    return _read_json(CONFIG_FILE, {})


def _save_player_config(data):
    _write_json(CONFIG_FILE, data)


_enforce_cache = {"at": 0.0}


def recover_allowlist_side_effects():
    """Undo allow-list auto enable from older BAN logic (runs once)."""
    cfg = _load_player_config()
    if cfg.get("allowlist_recovered_at"):
        return False
    legacy_auto = bool(cfg.get("allowlist_auto_enabled"))
    if not legacy_auto and _allow_list_enabled() and _load_banlist():
        legacy_auto = True
    if not legacy_auto or not _allow_list_enabled():
        return False
    if not write_properties({"allow-list": "false"}):
        return False
    try:
        _safe_write_bedrock_json("allowlist", [])
    except RuntimeError:
        pass
    cfg.pop("allowlist_auto_enabled", None)
    cfg["allowlist_recovered_at"] = _now_iso()
    _save_player_config(cfg)
    if _server_running():
        _restart_bedrock_and_wait()
    return True


def _kick_player(name, reason=""):
    if not _console_ready():
        return False
    cmd = f"kick {name} {reason}".strip()
    ok, _ = _send_console(cmd)
    return ok


def _read_server_properties():
    props = {}
    try:
        for line in (MINECRAFT_DIR / "server.properties").read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            props[key.strip()] = val.strip()
    except OSError:
        pass
    return props


def _allow_list_enabled():
    return _read_server_properties().get("allow-list", "false").lower() == "true"


def _enable_allow_list():
    if _allow_list_enabled():
        return False
    if not write_properties({"allow-list": "true"}):
        raise RuntimeError("allow-list の有効化に失敗しました")
    return True


def _allowlist_kind():
    if (MINECRAFT_DIR / "whitelist.json").exists():
        return "whitelist"
    return "allowlist"


def _sync_allowlist_file():
    entries = _build_allowlist_entries()
    _safe_write_bedrock_json(_allowlist_kind(), entries)


def _apply_ban_enforcement(restart_if_needed=True):
    """Enable allow-list and allowlist.json excluding banned players."""
    cfg = _load_player_config()
    prop_changed = _enable_allow_list()
    _sync_allowlist_file()
    cfg["ban_allowlist_enforcement"] = True
    _save_player_config(cfg)
    if prop_changed and restart_if_needed:
        _restart_bedrock_and_wait()
    elif _console_ready():
        _send_console("allowlist reload")
    return prop_changed


def _release_ban_enforcement_if_idle(restart_if_needed=True):
    if _load_banlist():
        return False
    cfg = _load_player_config()
    if not cfg.get("ban_allowlist_enforcement"):
        return False
    write_properties({"allow-list": "false"})
    try:
        _safe_write_bedrock_json("allowlist", [])
    except RuntimeError:
        pass
    cfg.pop("ban_allowlist_enforcement", None)
    _save_player_config(cfg)
    if restart_if_needed and _server_running():
        _restart_bedrock_and_wait()
    return True


def _ensure_ban_enforcement_sync():
    if not _load_banlist():
        return _release_ban_enforcement_if_idle(restart_if_needed=True)
    cfg = _load_player_config()
    if _allow_list_enabled() and cfg.get("ban_allowlist_enforcement"):
        _sync_allowlist_file()
        if _console_ready():
            _send_console("allowlist reload")
        return False
    return _apply_ban_enforcement(restart_if_needed=True)


def kick_if_banned(name, xuid=None):
    if not _is_banned(name=name, xuid=xuid):
        return False
    return _kick_player(name, "Banned")


def _banned_sets():
    names = set()
    xuids = set()
    for entry in _load_banlist():
        if entry.get("name"):
            names.add(entry["name"].lower())
        if entry.get("xuid"):
            xuids.add(str(entry["xuid"]))
    return names, xuids


def _build_allowlist_entries():
    banned_names, banned_xuids = _banned_sets()
    entries = []
    seen = set()
    reg = _load_registry().get("players", {})
    for key, row in reg.items():
        name = (row.get("name") or key).strip()
        if not name:
            continue
        xuid = str(row.get("xuid") or "")
        name_l = name.lower()
        if name_l in banned_names or (xuid and xuid in banned_xuids):
            continue
        if _is_deleted(name=name, xuid=xuid):
            continue
        dedupe = xuid or name_l
        if dedupe in seen:
            continue
        seen.add(dedupe)
        item = {"name": name, "ignoresPlayerLimit": False}
        if xuid:
            item["xuid"] = xuid
        entries.append(item)
    return entries


def enforce_banned_online():
    now = time.time()
    if now - _enforce_cache.get("at", 0) < 30:
        return
    if not _load_banlist():
        return
    from app.discord_manager import get_online_players
    online = get_online_players()
    if not online or not _console_ready():
        return
    kicked = False
    for name in online:
        if _is_banned(name=name):
            if _kick_player(name, "Banned"):
                kicked = True
    if kicked:
        _enforce_cache["at"] = now


def _normalize_permission(value):
    key = (value or "member").strip().lower()
    if key in PERMISSION_LABELS:
        return key
    return "member"


def _permission_label(value):
    return PERMISSION_LABELS.get(_normalize_permission(value), value)


def _load_registry():
    with _lock:
        data = _read_json(REGISTRY_FILE, {"players": {}})
        if "players" not in data:
            data["players"] = {}
        return data


def _save_registry(data):
    with _lock:
        _write_json(REGISTRY_FILE, data)


def _load_deleted():
    with _lock:
        data = _read_json(DELETED_FILE, {"names": [], "xuids": []})
        names = {n.lower() for n in data.get("names", []) if n}
        xuids = {str(x) for x in data.get("xuids", []) if x}
        return names, xuids


def _save_deleted(names, xuids):
    with _lock:
        _write_json(DELETED_FILE, {
            "names": sorted(names),
            "xuids": sorted(xuids),
        })


def _add_deleted(name, xuid=None):
    names, xuids = _load_deleted()
    if name:
        names.add(name.lower())
    if xuid:
        xuids.add(str(xuid))
    _save_deleted(names, xuids)


def _remove_deleted(name=None, xuid=None):
    names, xuids = _load_deleted()
    if name:
        names.discard(name.lower())
    if xuid:
        xuids.discard(str(xuid))
    _save_deleted(names, xuids)


def _is_deleted(name=None, xuid=None):
    names, xuids = _load_deleted()
    if name and name.lower() in names:
        return True
    if xuid and str(xuid) in xuids:
        return True
    return False


def _load_banlist():
    with _lock:
        data = _read_json(BANLIST_FILE, {"entries": []})
        return data.get("entries", [])


def _save_banlist(entries):
    with _lock:
        _write_json(BANLIST_FILE, {"entries": entries})


def _find_ban(name=None, xuid=None):
    name_l = (name or "").lower()
    xuid_s = str(xuid or "")
    for entry in _load_banlist():
        if name_l and (entry.get("name") or "").lower() == name_l:
            return entry
        if xuid_s and str(entry.get("xuid") or "") == xuid_s:
            return entry
    return None


def _is_banned(name=None, xuid=None):
    return _find_ban(name=name, xuid=xuid) is not None


def _add_ban(name, xuid=None):
    entries = _load_banlist()
    if _find_ban(name=name, xuid=xuid):
        return
    entries.insert(0, {
        "name": name,
        "xuid": str(xuid or ""),
        "banned_at": _now_iso(),
        "banned_at_label": _format_ts(_now_iso()),
    })
    _save_banlist(entries[:200])


def _remove_ban(name=None, xuid=None):
    entries = _load_banlist()
    name_l = (name or "").lower()
    xuid_s = str(xuid or "")
    new_entries = []
    removed = False
    for entry in entries:
        match = False
        if name_l and (entry.get("name") or "").lower() == name_l:
            match = True
        if xuid_s and str(entry.get("xuid") or "") == xuid_s:
            match = True
        if match:
            removed = True
            continue
        new_entries.append(entry)
    if removed:
        _save_banlist(new_entries)
    return removed


def track_player_join(name, xuid=None):
    name = (name or "").strip()
    if not name:
        return
    if _is_banned(name=name, xuid=xuid):
        kick_if_banned(name, xuid)
        return
    _remove_deleted(name=name, xuid=xuid)
    data = _load_registry()
    players = data.setdefault("players", {})
    key = name.lower()
    entry = {"name": name}
    if xuid:
        entry["xuid"] = str(xuid)
    now = _now_iso()
    entry["last_seen"] = now
    entry["first_seen"] = now
    players[key] = entry
    _save_registry(data)


def track_player_from_log_line(line):
    m = JOIN_XUID_RE.search(line)
    if m:
        name = m.group(1).strip()
        xuid = m.group(2).strip()
        if _is_deleted(name=name, xuid=xuid):
            return
        track_player_join(name, xuid)
        return
    m = JOIN_NAME_RE.search(line)
    if m:
        name = m.group(1).strip()
        if _is_deleted(name=name):
            return
        track_player_join(name)


_sync_cache = {"at": 0.0}
_SYNC_INTERVAL_SEC = 300


def sync_registry_from_journal():
    now = time.time()
    if now - _sync_cache.get("at", 0) < _SYNC_INTERVAL_SEC:
        return
    code, out, _ = _run(
        ["journalctl", "-u", "bedrock", "--no-pager", "-o", "cat", "--since", "7 days ago"],
        timeout=15,
    )
    if code != 0:
        return
    for line in out.splitlines():
        if "Player connected:" in line:
            track_player_from_log_line(line)
    _sync_cache["at"] = now


class PlayerBackend(ABC):
    @abstractmethod
    def list_players(self, online_names):
        pass

    @abstractmethod
    def change_permission(self, name, permission):
        pass

    @abstractmethod
    def ban_player(self, name):
        pass

    @abstractmethod
    def unban_player(self, name):
        pass

    @abstractmethod
    def kick_player(self, name):
        pass

    @abstractmethod
    def delete_player(self, name):
        pass


class BedrockPlayerBackend(PlayerBackend):
    def __init__(self):
        self.minecraft_dir = MINECRAFT_DIR

    def _allowlist_kind(self):
        if (self.minecraft_dir / "whitelist.json").exists():
            return "whitelist"
        return "allowlist"

    def _read_permissions(self):
        path = self.minecraft_dir / "permissions.json"
        data = _read_json(path, [])
        return data if isinstance(data, list) else []

    def _read_allowlist(self):
        kind = self._allowlist_kind()
        filename = "whitelist.json" if kind == "whitelist" else "allowlist.json"
        data = _read_json(self.minecraft_dir / filename, [])
        return data if isinstance(data, list) else [], kind

    def _default_permission(self):
        props = _read_server_properties()
        return _normalize_permission(props.get("default-player-permission-level", "member"))

    def _resolve_xuid(self, name):
        reg = _load_registry()
        entry = reg.get("players", {}).get(name.lower(), {})
        xuid = entry.get("xuid")
        if xuid:
            return str(xuid)
        ban = _find_ban(name=name)
        if ban and ban.get("xuid"):
            return str(ban["xuid"])
        allowlist, _kind = self._read_allowlist()
        for row in allowlist:
            if (row.get("name") or "").lower() == name.lower() and row.get("xuid"):
                return str(row["xuid"])
        return None

    def _permission_for_name(self, name, permissions, default_perm):
        xuid = self._resolve_xuid(name)
        if xuid:
            for item in permissions:
                if str(item.get("xuid", "")) == xuid:
                    return _normalize_permission(item.get("permission"))
        for item in permissions:
            if (item.get("name") or "").lower() == name.lower():
                return _normalize_permission(item.get("permission"))
        return default_perm

    def _write_allowlist(self, entries, kind):
        _safe_write_bedrock_json(kind, entries)

    def _sync_allowlist_for_bans(self):
        kind = self._allowlist_kind()
        entries = _build_allowlist_entries()
        self._write_allowlist(entries, kind)
        return kind

    def list_players(self, online_names):
        default_perm = self._default_permission()
        permissions = self._read_permissions()
        allowlist, allow_kind = self._read_allowlist()
        registry = _load_registry().get("players", {})
        online_set = {n.lower() for n in online_names}

        merged = {}
        for key, entry in registry.items():
            name = entry.get("name") or key
            if _is_deleted(name=name, xuid=entry.get("xuid")):
                continue
            merged[key] = {
                "name": name,
                "xuid": entry.get("xuid") or "",
                "first_seen": entry.get("first_seen") or "",
                "last_seen": entry.get("last_seen") or "",
            }

        for row in allowlist:
            name = (row.get("name") or "").strip()
            if not name or _is_deleted(name=name, xuid=row.get("xuid")):
                continue
            key = name.lower()
            if key not in merged:
                merged[key] = {
                    "name": name,
                    "xuid": str(row.get("xuid") or ""),
                    "first_seen": "",
                    "last_seen": "",
                }
            elif row.get("xuid") and not merged[key].get("xuid"):
                merged[key]["xuid"] = str(row["xuid"])

        players = []
        for entry in merged.values():
            name = entry["name"]
            xuid = entry.get("xuid") or ""
            if _is_banned(name=name, xuid=xuid):
                continue
            perm = self._permission_for_name(name, permissions, default_perm)
            players.append({
                "name": name,
                "online": name.lower() in online_set,
                "permission": perm,
                "permission_label": _permission_label(perm),
                "first_seen": entry.get("first_seen") or "",
                "last_seen": entry.get("last_seen") or "",
                "first_seen_label": _format_ts(entry.get("first_seen")),
                "last_seen_label": _format_ts(entry.get("last_seen")),
                "xuid": xuid,
                "banned": False,
                "allowlist_kind": allow_kind,
            })
        return players

    def _upsert_permission(self, name, permission):
        permission = _normalize_permission(permission)
        permissions = self._read_permissions()
        xuid = self._resolve_xuid(name)
        if not xuid:
            raise RuntimeError("XUIDが不明なため権限を変更できません。一度サーバーに参加してください。")

        updated = []
        found = False
        for item in permissions:
            if str(item.get("xuid", "")) == xuid:
                found = True
                if permission != self._default_permission():
                    updated.append({"permission": permission, "xuid": xuid})
            else:
                updated.append(item)
        if not found and permission != self._default_permission():
            updated.append({"permission": permission, "xuid": xuid})
        _safe_write_bedrock_json("permissions", updated)
        return permission

    def change_permission(self, name, permission):
        permission = _normalize_permission(permission)
        self._upsert_permission(name, permission)
        reloaded = False
        if _ensure_console():
            ok, _ = _send_console("permission reload")
            reloaded = ok
        return {
            "success": True,
            "message": "権限を更新しました" + ("" if reloaded else "（permission reload は未実行）"),
            "needs_restart": not reloaded,
            "permission": permission,
        }

    def ban_player(self, name):
        xuid = self._resolve_xuid(name)
        _add_ban(name, xuid)
        _apply_ban_enforcement(restart_if_needed=True)
        kicked = _kick_player(name, "Banned")
        msg = f"{name} をBANしました"
        if kicked:
            msg += "（キック済み）"
        else:
            msg += "（接続拒否を適用しました）"
        return {"success": True, "message": msg, "needs_restart": False}

    def unban_player(self, name):
        ban = _find_ban(name=name)
        if not ban:
            return {"success": False, "message": "BANリストに登録されていません", "needs_restart": False}
        player_name = ban.get("name") or name
        xuid = ban.get("xuid")
        _remove_ban(name=player_name, xuid=xuid)
        if _load_banlist():
            if _allow_list_enabled():
                entries = _build_allowlist_entries()
                kind = self._allowlist_kind()
                self._write_allowlist(entries, kind)
                if _console_ready():
                    _send_console("allowlist reload")
        else:
            _release_ban_enforcement_if_idle(restart_if_needed=True)
        return {"success": True, "message": f"{player_name} のBANを解除しました", "needs_restart": False}

    def kick_player(self, name):
        if not _server_running():
            return {"success": False, "message": "サーバーが起動していません", "needs_restart": False}
        if not _console_ready():
            return {
                "success": False,
                "message": "Kickできません。ホーム画面からサーバーを一度再起動してください",
                "needs_restart": False,
            }
        ok, err = _send_console(f"kick {name}")
        if not ok:
            return {"success": False, "message": err, "needs_restart": False}
        return {"success": True, "message": f"{name} をキックしました", "needs_restart": False}

    def _remove_from_permissions(self, xuid):
        if not xuid:
            return
        permissions = self._read_permissions()
        updated = [p for p in permissions if str(p.get("xuid", "")) != str(xuid)]
        if len(updated) != len(permissions):
            _safe_write_bedrock_json("permissions", updated)
            if _ensure_console():
                _send_console("permission reload")

    def delete_player(self, name):
        reg = _load_registry()
        key = name.lower()
        entry = reg.get("players", {}).get(key, {})
        xuid = entry.get("xuid") or self._resolve_xuid(name)

        if key in reg.get("players", {}):
            del reg["players"][key]
            _save_registry(reg)

        _add_deleted(name, xuid)
        self._remove_from_permissions(xuid)
        if _allow_list_enabled():
            self._sync_allowlist_for_bans()
            if _ensure_console():
                _send_console("allowlist reload")

        if _ensure_console():
            _send_console(f"kick {name}")

        return {
            "success": True,
            "message": f"{name} を削除しました。再参加時は新規登録されます。",
            "needs_restart": False,
        }


def _format_ts(iso_value):
    if not iso_value:
        return "-"
    try:
        dt = datetime.fromisoformat(iso_value.replace("Z", "+00:00"))
        if dt.tzinfo:
            dt = dt.astimezone().replace(tzinfo=None)
        return dt.strftime("%Y/%m/%d %H:%M")
    except ValueError:
        return iso_value


def get_backend(game_type=None):
    game = (game_type or _detect_game_type()).lower()
    if game == "bedrock":
        return BedrockPlayerBackend()
    raise RuntimeError(f"未対応のゲーム種別: {game}")


def _detect_game_type():
    return "bedrock"


def list_players(online_names=None, sort="online", query=""):
    if online_names is None:
        from app.discord_manager import get_online_players
        online_names = get_online_players()
    backend = get_backend()
    players = backend.list_players(online_names)
    q = (query or "").strip().lower()
    if q:
        players = [
            p for p in players
            if q in p["name"].lower() or q in (p.get("xuid") or "").lower()
        ]
    sort_key = (sort or "online").lower()
    if sort_key == "name":
        players.sort(key=lambda p: p["name"].lower())
    elif sort_key == "joined":
        players.sort(key=lambda p: p.get("first_seen") or "", reverse=True)
    else:
        players.sort(key=lambda p: (0 if p["online"] else 1, p["name"].lower()))
    return {
        "players": players,
        "online_count": sum(1 for p in players if p["online"]),
        "total_count": len(players),
        "game_type": _detect_game_type(),
    }


def _migrate_legacy_bans():
    reg = _load_registry()
    players = reg.get("players", {})
    changed = False
    for key, entry in players.items():
        if not entry.get("banned"):
            continue
        _add_ban(entry.get("name") or key, entry.get("xuid"))
        entry.pop("banned", None)
        changed = True
    if changed:
        _save_registry(reg)


def get_banlist():
    _migrate_legacy_bans()
    _ensure_ban_enforcement_sync()
    entries = []
    for row in _load_banlist():
        entries.append({
            "name": row.get("name") or "",
            "xuid": row.get("xuid") or "",
            "banned_at": row.get("banned_at") or "",
            "banned_at_label": row.get("banned_at_label") or _format_ts(row.get("banned_at")),
        })
    return {"entries": entries}


def get_home_summary():
    from app.discord_manager import get_online_players
    online = get_online_players()
    return {
        "online_count": len(online),
        "players": [{"name": n, "online": True} for n in online],
    }


def perform_action(action, name, permission=None):
    backend = get_backend()
    action = (action or "").strip().lower()
    name = (name or "").strip()
    if not name:
        raise ValueError("プレイヤー名が必要です")

    if action == "permission":
        if not permission:
            raise ValueError("権限が必要です")
        return backend.change_permission(name, permission)
    if action == "ban":
        return backend.ban_player(name)
    if action == "unban":
        return backend.unban_player(name)
    if action == "kick":
        return backend.kick_player(name)
    if action == "delete":
        return backend.delete_player(name)
    raise ValueError(f"未対応の操作: {action}")


def reset_all_players(restart_if_needed=True):
    """Reset player registry, bans, and Minecraft permissions/allowlist."""
    _write_json(REGISTRY_FILE, {"players": {}})
    _write_json(BANLIST_FILE, {"entries": []})
    _write_json(DELETED_FILE, {"names": [], "xuids": []})
    _write_json(CONFIG_FILE, {})
    try:
        _safe_write_bedrock_json("permissions", [])
        _safe_write_bedrock_json("allowlist", [])
    except RuntimeError:
        (MINECRAFT_DIR / "permissions.json").write_text("[]\n", encoding="utf-8")
        (MINECRAFT_DIR / "allowlist.json").write_text("[]\n", encoding="utf-8")
    write_properties({"allow-list": "false"})
    restarted = _release_ban_enforcement_if_idle(restart_if_needed=restart_if_needed)
    if _console_ready() and not restarted:
        _send_console("permission reload")
        _send_console("allowlist reload")
