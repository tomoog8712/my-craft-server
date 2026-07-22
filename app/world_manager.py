"""World manager for Minecraft Bedrock Dedicated Server."""

import json
import os
import re
import shutil
import subprocess
import tarfile
import threading
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from app.settings_manager import read_properties, write_properties
from app.update_manager import wait_for_running

MINECRAFT_DIR = Path("/opt/minecraft")
WORLDS_DIR = MINECRAFT_DIR / "worlds"
DATA_DIR = Path("/opt/appliance/data")
PLAYER_CONFIG_FILE = DATA_DIR / "config.json"
WORLDS_DATA = DATA_DIR / "worlds"
REGISTRY_FILE = WORLDS_DATA / "registry.json"
WORLD_BACKUP_DIR = WORLDS_DATA / "backups"
WORK_DIR = Path("/opt/appliance/work")
DEATH_NOTIFY_SCRIPT = "/opt/appliance/bin/world-enable-death-notify.sh"
CONSOLE_SCRIPT = "/opt/appliance/bin/bedrock-console-send.sh"
DEATH_NOTIFY_PACK_ID = "c8f4a2b1-3d5e-4f6a-9b0c-1d2e3f4a5b6c"

PLAYTIME_FILE = WORLDS_DATA / "playtime.json"

MAX_WORLD_BACKUPS = 10
LEVEL_NAME_RE = re.compile(r'^[^\\/:*?"<>|\r\n\t\f`]+$')

WORLD_PROPERTY_KEYS = [
    "level-name",
    "level-seed",
    "gamemode",
    "difficulty",
    "allow-cheats",
    "force-gamemode",
    "default-player-permission-level",
    "max-players",
    "pvp",
    "show-coordinates",
]

GAMEMODE_MAP = {"survival": "survival", "creative": "creative", "adventure": "adventure"}
DIFFICULTY_MAP = {"peaceful": "peaceful", "easy": "easy", "normal": "normal", "hard": "hard"}

DEFAULT_WORLD_RULES = {
    "spawn_protection": "true",
    "achievements": "true",
    "daylight_cycle": "true",
    "weather": "true",
    "immediate_respawn": "false",
    "mob_spawn": "true",
    "mob_griefing": "true",
    "tnt": "true",
    "fire_spread": "true",
    "command_blocks_enabled": "true",
}

# Internal rule key -> (Bedrock gamerule name, value kind: bool|int)
GAMERULE_MAP = {
    "spawn_protection": ("spawnradius", "int"),
    "daylight_cycle": ("dodaylightcycle", "bool"),
    "weather": ("doweathercycle", "bool"),
    "immediate_respawn": ("doimmediaterespawn", "bool"),
    "mob_spawn": ("domobspawning", "bool"),
    "mob_griefing": ("mobgriefing", "bool"),
    "tnt": ("tntexplodes", "bool"),
    "fire_spread": ("dofiretick", "bool"),
    "command_blocks_enabled": ("commandblocksenabled", "bool"),
}

# server.properties keys applied live via Bedrock console (no restart).
# max-players is persisted in server.properties only; Bedrock rejects changesetting max-players.
LIVE_CHANGESETTING_MAP = {
    "allow-cheats": "allow-cheats",
    "difficulty": "difficulty",
}

# server.properties keys mirrored as gamerules on a running world.
LIVE_PROP_GAMERULE_MAP = {
    "pvp": "pvp",
    "show-coordinates": "showcoordinates",
}

# UI/API metadata: which settings apply live vs need a server restart.
WORLD_SETTING_APPLY = {
    "gamemode": {"mode": "live", "label_ja": "ゲームモード"},
    "difficulty": {"mode": "live", "label_ja": "難易度"},
    "max_players": {"mode": "live", "label_ja": "最大人数"},
    "seed": {"mode": "restart", "label_ja": "シード値", "hint_ja": "再起動後に有効（既存の地形は変わりません）"},
    "pvp": {"mode": "live", "label_ja": "PvP"},
    "show-coordinates": {"mode": "live", "label_ja": "座標表示"},
    "allow-cheats": {"mode": "live", "label_ja": "チート許可"},
    "force-gamemode": {"mode": "live", "label_ja": "ゲームモード強制"},
    "command_blocks_enabled": {"mode": "live", "label_ja": "コマンドブロック"},
    "spawn_protection": {"mode": "live", "label_ja": "初期スポーン保護"},
    "achievements": {"mode": "restart", "label_ja": "実績", "hint_ja": "再起動後に有効"},
    "daylight_cycle": {"mode": "live", "label_ja": "昼夜サイクル"},
    "weather": {"mode": "live", "label_ja": "天候変化"},
    "immediate_respawn": {"mode": "live", "label_ja": "即時リスポーン"},
    "mob_spawn": {"mode": "live", "label_ja": "Mobスポーン"},
    "mob_griefing": {"mode": "live", "label_ja": "Mobによる破壊"},
    "tnt": {"mode": "live", "label_ja": "TNT爆発"},
    "fire_spread": {"mode": "live", "label_ja": "火の延焼"},
}

RESTART_SETTING_KEYS = {k for k, v in WORLD_SETTING_APPLY.items() if v.get("mode") == "restart"}

_lock = threading.Lock()
_playtime_lock = threading.Lock()
_REGISTRY_CACHE = {"data": None, "at": 0.0}
REGISTRY_CACHE_TTL = 30


def get_active_world_folder():
    _, props = read_properties()
    return props.get("level-name", "")


def _format_play_time(seconds):
    seconds = max(0, int(seconds))
    if seconds < 60:
        return "1分未満"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}分"
    hours = minutes // 60
    rem = minutes % 60
    if hours < 24:
        return f"{hours}時間{rem}分" if rem else f"{hours}時間"
    days = hours // 24
    hours = hours % 24
    return f"{days}日{hours}時間" if hours else f"{days}日"


def _load_playtime():
    return _read_json(PLAYTIME_FILE, {})


def _save_playtime(data):
    _write_json(PLAYTIME_FILE, data)


def clear_active_play_sessions():
    with _playtime_lock:
        data = _load_playtime()
        changed = False
        for world_data in data.values():
            if world_data.get("sessions"):
                world_data["sessions"] = {}
                changed = True
        if changed:
            _save_playtime(data)


def track_player_join(player):
    world = get_active_world_folder()
    if not world or not player:
        return
    with _playtime_lock:
        data = _load_playtime()
        world_data = data.setdefault(world, {"total_seconds": 0, "sessions": {}})
        sessions = world_data.setdefault("sessions", {})
        if player not in sessions:
            sessions[player] = time.time()
        _save_playtime(data)


def track_player_leave(player):
    world = get_active_world_folder()
    if not world or not player:
        return
    with _playtime_lock:
        data = _load_playtime()
        world_data = data.get(world)
        if not world_data:
            return
        sessions = world_data.setdefault("sessions", {})
        started = sessions.pop(player, None)
        if started:
            world_data["total_seconds"] = int(world_data.get("total_seconds", 0) + max(0, time.time() - started))
        _save_playtime(data)


def get_play_time_seconds(world_folder):
    with _playtime_lock:
        data = _load_playtime()
        world_data = data.get(world_folder, {})
        total = int(world_data.get("total_seconds", 0))
        now = time.time()
        for started in world_data.get("sessions", {}).values():
            total += max(0, int(now - started))
        return total


def get_play_time_label(world_folder):
    total = get_play_time_seconds(world_folder)
    return _format_play_time(total) if total > 0 else "-"


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _now_id():
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _read_json(path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default if default is not None else {}


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _run(cmd, timeout=120):
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        return 1, "", str(exc)


def _systemctl(action):
    code, out, err = _run(["sudo", "-n", "/usr/bin/systemctl", action, "bedrock"], timeout=90)
    return code == 0, err or out


def _slugify(name):
    base = re.sub(r"[^\w\s-]", "", name, flags=re.UNICODE).strip().lower()
    base = re.sub(r"[-\s]+", "-", base)
    return base or "world"


def _format_size(num_bytes):
    if num_bytes < 1024 * 1024:
        return f"{max(1, num_bytes // 1024)} KB"
    if num_bytes < 1024 * 1024 * 1024:
        return f"{num_bytes / (1024 * 1024):.1f} MB"
    return f"{num_bytes / (1024 * 1024 * 1024):.2f} GB"


def _dir_size(path):
    total = 0
    try:
        for root, _dirs, files in os.walk(path):
            for fname in files:
                try:
                    total += (Path(root) / fname).stat().st_size
                except OSError:
                    pass
    except OSError:
        return 0
    return total


def _profile_path(world_id):
    return WORLDS_DATA / "profiles" / f"{world_id}.json"


def _load_registry():
    reg = _read_json(REGISTRY_FILE, {"active_id": None, "worlds": {}})
    if "worlds" not in reg:
        reg["worlds"] = {}
    return reg


def _save_registry(reg):
    _write_json(REGISTRY_FILE, reg)


def _read_props_dict():
    _, values = read_properties()
    return values


def _snapshot_properties(folder_name):
    props = _read_props_dict()
    snap = {k: props.get(k, "") for k in WORLD_PROPERTY_KEYS}
    snap["level-name"] = folder_name
    return snap


def _save_profile(world_id, entry):
    _write_json(_profile_path(world_id), entry)


def _load_profile(world_id):
    return _read_json(_profile_path(world_id), {})


def _apply_properties(updates):
    write_properties(updates)


def _ban_allowlist_enforcement_active():
    try:
        cfg = json.loads(PLAYER_CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return bool(cfg.get("ban_allowlist_enforcement"))


def _ensure_open_join_settings():
    """Allow anyone to join unless ban enforcement intentionally uses allow-list."""
    if _ban_allowlist_enforcement_active():
        return
    write_properties({"allow-list": "false"})
    (MINECRAFT_DIR / "allowlist.json").write_text("[]\n", encoding="utf-8")


def _send_bedrock_command(command):
    code, out, err = _run(["sudo", "-n", CONSOLE_SCRIPT, command], timeout=10)
    return code == 0 and out == "OK"


def _gamerule_value(rule_key, enabled):
    on = str(enabled).lower() == "true"
    _kind = GAMERULE_MAP.get(rule_key, (None, None))[1]
    if _kind == "int":
        return "5" if on else "0"
    return "true" if on else "false"


def _apply_world_rules(rules):
    if not _world_running():
        return False
    applied = False
    for rule_key, (gamerule, _kind) in GAMERULE_MAP.items():
        if rule_key not in rules:
            continue
        value = _gamerule_value(rule_key, rules.get(rule_key))
        if _send_bedrock_command(f"gamerule {gamerule} {value}"):
            applied = True
        time.sleep(0.05)
    return applied


def _apply_live_gamemode(props, gamemode_changed=False, force_gamemode_changed=False):
    gamemode = props.get("gamemode")
    if not gamemode:
        return False
    force = str(props.get("force-gamemode", "false")).lower() == "true"
    if not (gamemode_changed or (force_gamemode_changed and force)):
        return False
    applied = False
    try:
        from app.discord_manager import get_online_players
        players = get_online_players()
    except Exception:
        players = []
    if players:
        for player in players:
            if _send_bedrock_command(f"gamemode {gamemode} {player}"):
                applied = True
            time.sleep(0.05)
    elif _send_bedrock_command(f"gamemode {gamemode} @a"):
        applied = True
    return applied


def _apply_live_max_players(max_players):
    value = str(max_players or "").strip()
    if not value.isdigit():
        return False
    return _send_bedrock_command(f"setmaxplayers {value}")


def _apply_live_world_settings(props, rules, gamemode_changed=False, force_gamemode_changed=False):
    """Push world settings to a running Bedrock server without restart."""
    if not _world_running():
        return False
    applied = False
    for prop_key, setting_name in LIVE_CHANGESETTING_MAP.items():
        value = props.get(prop_key)
        if value is None or value == "":
            continue
        if _send_bedrock_command(f"changesetting {setting_name} {value}"):
            applied = True
        time.sleep(0.05)
    if _apply_live_max_players(props.get("max-players")):
        applied = True
    for prop_key, gamerule in LIVE_PROP_GAMERULE_MAP.items():
        value = props.get(prop_key)
        if value is None:
            continue
        bool_val = "true" if str(value).lower() == "true" else "false"
        if _send_bedrock_command(f"gamerule {gamerule} {bool_val}"):
            applied = True
        time.sleep(0.05)
    if _apply_live_gamemode(props, gamemode_changed, force_gamemode_changed):
        applied = True
    if _apply_world_rules(rules):
        applied = True
    return applied


def _collect_restart_required_fields(data, profile, props, rules, seed):
    pending = []
    prev_seed = str(profile.get("seed") or props.get("level-seed", "")).strip()
    if str(seed).strip() != prev_seed:
        pending.append("seed")
    prev_rules = dict(DEFAULT_WORLD_RULES)
    prev_rules.update(profile.get("rules") or {})
    if "achievements" in data and rules.get("achievements") != prev_rules.get("achievements"):
        pending.append("achievements")
    return [key for key in pending if key in RESTART_SETTING_KEYS]


def _restart_field_labels(field_keys):
    labels = []
    for key in field_keys:
        meta = WORLD_SETTING_APPLY.get(key, {})
        labels.append(meta.get("label_ja") or key)
    return labels


def _invalidate_registry_cache():
    _REGISTRY_CACHE["data"] = None
    _REGISTRY_CACHE["at"] = 0.0


def _apply_active_world_rules():
    reg = sync_registry()
    active_id = reg.get("active_id")
    if not active_id:
        return False
    profile = _load_profile(active_id)
    rules = dict(DEFAULT_WORLD_RULES)
    rules.update(profile.get("rules") or {})
    return _apply_world_rules(rules)


def _find_world_data_dir(path):
    """Return directory that directly contains level.dat."""
    root = Path(path)
    if (root / "level.dat").is_file():
        return root
    for child in sorted(root.iterdir()):
        if child.is_dir() and (child / "level.dat").is_file():
            return child
    raise ValueError("有効なBedrockワールド（level.dat）が見つかりません")


def _read_levelname(path):
    levelname = Path(path) / "levelname.txt"
    try:
        return levelname.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _validate_level_name(name):
    name = (name or "").strip()
    if not name or len(name) > 64:
        raise ValueError("ワールド名が無効です")
    if not LEVEL_NAME_RE.fullmatch(name):
        raise ValueError("ワールド名に使えない文字が含まれています")
    return name


def _folder_mtime_label(path):
    try:
        ts = path.stat().st_mtime
        dt = datetime.fromtimestamp(ts)
        delta = datetime.now() - dt
        if delta.days == 0:
            return "今日"
        if delta.days == 1:
            return "昨日"
        if delta.days < 7:
            return f"{delta.days}日前"
        return dt.strftime("%Y-%m-%d")
    except OSError:
        return "-"


def _world_running():
    code, out, _ = _run(["systemctl", "is-active", "bedrock"], timeout=5)
    return code == 0 and out == "active"


def _is_valid_world_dir(path):
    return Path(path).is_dir() and (Path(path) / "level.dat").is_file()


def _registry_id_for_folder(worlds, folder):
    for wid, entry in worlds.items():
        if entry.get("folder") == folder:
            return wid
    return _slugify(folder)


def _unique_world_id(base_id, folder, assigned):
    world_id = base_id or "world"
    if world_id not in assigned or assigned[world_id] == folder:
        return world_id
    suffix = 2
    while True:
        candidate = f"{world_id}-{suffix}"
        if candidate not in assigned or assigned[candidate] == folder:
            return candidate
        suffix += 1


def sync_registry(force=False):
    now = time.time()
    if (
        not force
        and _REGISTRY_CACHE["data"] is not None
        and now - _REGISTRY_CACHE["at"] < REGISTRY_CACHE_TTL
    ):
        return _REGISTRY_CACHE["data"]
    reg = _load_registry()
    old_worlds = reg.get("worlds", {})
    _, props = read_properties()
    active_folder = props.get("level-name", "Bedrock level")
    assigned = {}
    new_worlds = {}

    if WORLDS_DIR.exists():
        for child in sorted(WORLDS_DIR.iterdir(), key=lambda p: p.name.lower()):
            if not _is_valid_world_dir(child):
                continue
            folder = child.name
            base_id = _registry_id_for_folder(old_worlds, folder)
            world_id = _unique_world_id(base_id, folder, assigned)
            assigned[world_id] = folder

            profile = _load_profile(world_id)
            entry = dict(old_worlds.get(world_id, {}))
            entry.update({
                "id": world_id,
                "folder": folder,
                "display_name": profile.get("display_name") or folder,
                "description": profile.get("description", ""),
                "icon": profile.get("icon", "default"),
                "created_at": entry.get("created_at") or profile.get("created_at") or _now_iso(),
                "last_played_at": profile.get("last_played_at"),
                "size_bytes": (size_bytes := _dir_size(child)),
                "size_label": _format_size(size_bytes),
                "last_played_label": _folder_mtime_label(child),
                "gamemode": profile.get("gamemode") or props.get("gamemode", "survival"),
                "difficulty": profile.get("difficulty") or props.get("difficulty", "normal"),
                "seed": profile.get("seed") or props.get("level-seed", ""),
                "active": folder == active_folder,
                "server_running": _world_running(),
            })
            if folder == active_folder:
                entry["gamemode"] = props.get("gamemode", entry["gamemode"])
                entry["difficulty"] = props.get("difficulty", entry["difficulty"])
                reg["active_id"] = world_id
            new_worlds[world_id] = entry
            if not profile:
                profile = {"properties": _snapshot_properties(folder), **entry}
                _save_profile(world_id, profile)

    reg["worlds"] = new_worlds
    if reg.get("active_id") not in new_worlds:
        reg["active_id"] = None
        for wid, w in new_worlds.items():
            if w.get("active"):
                reg["active_id"] = wid
                break
    _save_registry(reg)
    _REGISTRY_CACHE["data"] = reg
    _REGISTRY_CACHE["at"] = time.time()
    return reg


def _public_world(entry, players_online=0, players=None):
    active_players = list(players or [])
    if not (entry.get("active") and entry.get("server_running")):
        players_online = 0
        active_players = []
    return {
        "id": entry["id"],
        "folder": entry["folder"],
        "display_name": entry.get("display_name") or entry["folder"],
        "description": entry.get("description", ""),
        "icon": entry.get("icon", "default"),
        "gamemode": entry.get("gamemode", "survival"),
        "difficulty": entry.get("difficulty", "normal"),
        "seed": entry.get("seed", ""),
        "size_label": entry.get("size_label", "-"),
        "size_bytes": entry.get("size_bytes", 0),
        "last_played_label": entry.get("last_played_label", "-"),
        "created_at": entry.get("created_at"),
        "active": entry.get("active", False),
        "server_running": entry.get("server_running", False),
        "players_online": players_online,
        "players": active_players,
        "players_max": int(_read_props_dict().get("max-players", "10")),
        "play_time_label": get_play_time_label(entry["folder"]),
    }


def list_worlds():
    with _lock:
        reg = sync_registry()
        entries = list(reg["worlds"].values())
        active_id = reg.get("active_id")

    players_online = 0
    players = []
    if any(e.get("active") and e.get("server_running") for e in entries):
        try:
            from app.discord_manager import get_online_player_count, get_online_players
            players_online = get_online_player_count()
            players = get_online_players()
        except Exception:
            players_online = 0
            players = []

    worlds = [_public_world(w, players_online, players) for w in entries]
    worlds.sort(key=lambda w: (not w["active"], w["display_name"].lower()))
    return {"worlds": worlds, "active_id": active_id}


def get_current_world():
    data = list_worlds()
    active = next((w for w in data["worlds"] if w["active"]), None)
    return {"world": active, "active_id": data.get("active_id")}


def get_world(world_id):
    reg = sync_registry()
    entry = reg["worlds"].get(world_id)
    if not entry:
        raise ValueError("ワールドが見つかりません")
    profile = _load_profile(world_id)
    result = _public_world(entry)
    result["description"] = profile.get("description", "")
    result["properties"] = profile.get("properties", {})
    result["rules"] = profile.get("rules", {})
    return result


def _bool_setting(val, default=False):
    if val is None:
        return "true" if default else "false"
    return "true" if str(val).lower() in ("true", "1", "on", "yes") else "false"


def get_world_settings(world_id):
    world = get_world(world_id)
    props = world.get("properties") or {}
    rules = dict(DEFAULT_WORLD_RULES)
    rules.update(world.get("rules") or {})
    return {
        "world_id": world_id,
        "display_name": world.get("display_name", ""),
        "active": bool(world.get("active")),
        "gamemode": world.get("gamemode") or props.get("gamemode", "survival"),
        "difficulty": world.get("difficulty") or props.get("difficulty", "normal"),
        "seed": world.get("seed") or props.get("level-seed", ""),
        "max_players": props.get("max-players", "10"),
        "pvp": props.get("pvp", "true"),
        "show-coordinates": props.get("show-coordinates", "false"),
        "allow-cheats": props.get("allow-cheats", "false"),
        "force-gamemode": props.get("force-gamemode", "false"),
        "default-player-permission-level": props.get("default-player-permission-level", "member"),
        "rules": rules,
        "field_apply": WORLD_SETTING_APPLY,
    }


def save_world_settings(world_id, data):
    with _lock:
        reg = sync_registry()
        if world_id not in reg["worlds"]:
            raise ValueError("ワールドが見つかりません")
        entry = reg["worlds"][world_id]
        folder = entry["folder"]
        profile = _load_profile(world_id)
        props = dict(profile.get("properties") or _snapshot_properties(folder))
        props["level-name"] = folder

        gamemode = GAMEMODE_MAP.get(
            str(data.get("gamemode", profile.get("gamemode", props.get("gamemode", "survival")))).lower(),
            "survival",
        )
        difficulty = DIFFICULTY_MAP.get(
            str(data.get("difficulty", profile.get("difficulty", props.get("difficulty", "normal")))).lower(),
            "normal",
        )
        seed = str(data.get("seed") or data.get("level-seed") or profile.get("seed") or props.get("level-seed", "")).strip()
        max_players = str(
            data.get("max_players")
            or data.get("max-players")
            or props.get("max-players", "10")
        )

        props["level-seed"] = seed
        props["gamemode"] = gamemode
        props["difficulty"] = difficulty
        props["max-players"] = max_players
        props["pvp"] = _bool_setting(data.get("pvp", props.get("pvp")), True)
        props["show-coordinates"] = _bool_setting(data.get("show-coordinates", props.get("show-coordinates")), False)
        props["allow-cheats"] = _bool_setting(data.get("allow-cheats", props.get("allow-cheats")), False)
        prev_gamemode = profile.get("gamemode") or props.get("gamemode", "survival")
        prev_force_gamemode = props.get("force-gamemode", "false")
        gamemode_changed = data.get("gamemode") is not None and gamemode != prev_gamemode
        props["force-gamemode"] = _bool_setting(data.get("force-gamemode", props.get("force-gamemode")), False)
        force_gamemode_changed = (
            "force-gamemode" in data
            and props["force-gamemode"] != prev_force_gamemode
        )
        if gamemode_changed:
            # Existing Bedrock worlds keep creation-time gamemode unless forced.
            props["force-gamemode"] = "true"
            force_gamemode_changed = props["force-gamemode"] != prev_force_gamemode
        if data.get("default-player-permission-level") is not None:
            props["default-player-permission-level"] = str(data["default-player-permission-level"])
        elif "default-player-permission-level" not in props:
            props["default-player-permission-level"] = "member"

        rules = dict(DEFAULT_WORLD_RULES)
        rules.update(profile.get("rules") or {})
        for rule_key in DEFAULT_WORLD_RULES:
            if rule_key in data:
                rules[rule_key] = _bool_setting(data[rule_key], rules.get(rule_key) == "true")

        profile["properties"] = props
        profile["gamemode"] = gamemode
        profile["difficulty"] = difficulty
        profile["seed"] = seed
        profile["rules"] = rules
        _save_profile(world_id, profile)

        entry["gamemode"] = gamemode
        entry["difficulty"] = difficulty
        entry["seed"] = seed
        reg["worlds"][world_id] = entry
        _save_registry(reg)
        _invalidate_registry_cache()

        restart_required_fields = _collect_restart_required_fields(data, profile, props, rules, seed)

        is_active = reg.get("active_id") == world_id
        restarted = False
        applied_live = False
        if is_active:
            property_updates = {
                k: v for k, v in props.items()
                if k in WORLD_PROPERTY_KEYS and v is not None
            }
            _apply_properties(property_updates)
            if _world_running():
                applied_live = _apply_live_world_settings(
                    props,
                    rules,
                    gamemode_changed,
                    force_gamemode_changed,
                )
            else:
                _start_and_wait()
                restarted = True

        return True, {
            "needs_restart": bool(restart_required_fields) and is_active,
            "restart_required_fields": restart_required_fields,
            "restart_required_labels": _restart_field_labels(restart_required_fields),
            "restarted": restarted,
            "applied_live": applied_live,
            "world_id": world_id,
        }


def _stop_and_wait():
    ok, msg = _systemctl("stop")
    if not ok:
        raise RuntimeError(f"サーバー停止に失敗: {msg}")
    time.sleep(2)


def _start_and_wait():
    ok, msg = _systemctl("start")
    if not ok:
        raise RuntimeError(f"サーバー起動に失敗: {msg}")
    if not wait_for_running():
        raise RuntimeError("サーバーが起動しませんでした")
    time.sleep(3)
    _apply_active_world_rules()


def _save_active_snapshot():
    reg = _load_registry()
    active_id = reg.get("active_id")
    if not active_id or active_id not in reg["worlds"]:
        return
    entry = reg["worlds"][active_id]
    profile = _load_profile(active_id)
    profile["properties"] = _snapshot_properties(entry["folder"])
    profile["gamemode"] = _read_props_dict().get("gamemode", "survival")
    profile["difficulty"] = _read_props_dict().get("difficulty", "normal")
    profile["seed"] = _read_props_dict().get("level-seed", "")
    profile["last_played_at"] = _now_iso()
    _save_profile(active_id, profile)


def _ensure_death_notify_pack(world_folder):
    world_path = WORLDS_DIR / world_folder
    if not world_path.is_dir():
        return
    code, _, _ = _run(["sudo", "-n", DEATH_NOTIFY_SCRIPT, str(world_path)], timeout=15)
    if code != 0:
        pack_file = world_path / "world_behavior_packs.json"
        packs = _read_json(pack_file, [])
        if not isinstance(packs, list):
            packs = []
        entry = {"pack_id": DEATH_NOTIFY_PACK_ID, "version": [1, 0, 0]}
        if not any(p.get("pack_id") == DEATH_NOTIFY_PACK_ID for p in packs):
            packs.append(entry)
            try:
                _write_json(pack_file, packs)
            except OSError:
                pass


def _discord(event, **kwargs):
    try:
        from app.discord_manager import notify
        notify(event, **kwargs)
    except Exception:
        pass


def switch_world(world_id):
    with _lock:
        reg = sync_registry()
        if world_id not in reg["worlds"]:
            raise ValueError("ワールドが見つかりません")
        if reg.get("active_id") == world_id:
            return True, "すでに使用中です"

        from_world = reg["worlds"].get(reg.get("active_id"), {}).get("display_name", "-")
        target = reg["worlds"][world_id]
        folder = target["folder"]
        if not (WORLDS_DIR / folder).exists():
            raise ValueError("ワールドフォルダが見つかりません")

        _stop_and_wait()
        _save_active_snapshot()

        profile = _load_profile(world_id)
        props = profile.get("properties") or _snapshot_properties(folder)
        props["level-name"] = folder
        _apply_properties({k: v for k, v in props.items() if k in WORLD_PROPERTY_KEYS and v is not None})

        for wid, w in reg["worlds"].items():
            w["active"] = wid == world_id
        reg["active_id"] = world_id
        _save_registry(reg)

        profile["last_played_at"] = _now_iso()
        _save_profile(world_id, profile)

        _start_and_wait()
        _ensure_death_notify_pack(folder)
        _discord("world_switch", from_world=from_world, to_world=target.get("display_name", folder))
        return True, "ワールドを切り替えました"




def _sync_global_addons():
    try:
        from app.addon_manager import sync_addons_to_all_worlds
        sync_addons_to_all_worlds()
    except Exception:
        pass


def create_world(data):
    with _lock:
        name = _validate_level_name(data.get("name") or data.get("display_name"))
        world_id = _slugify(name)
        reg = _load_registry()
        suffix = 2
        base_id = world_id
        while world_id in reg["worlds"]:
            if reg["worlds"][world_id].get("folder") == name:
                raise ValueError("同じ名前のワールドが既にあります")
            world_id = f"{base_id}-{suffix}"
            suffix += 1

        gamemode = GAMEMODE_MAP.get(str(data.get("gamemode", "survival")).lower(), "survival")
        difficulty = DIFFICULTY_MAP.get(str(data.get("difficulty", "normal")).lower(), "normal")
        seed = str(data.get("seed") or data.get("level-seed") or "").strip()
        max_players = str(data.get("max_players") or data.get("max-players") or "10")

        def _bool(key, default=False):
            val = data.get(key)
            if val is None:
                return "true" if default else "false"
            return "true" if str(val).lower() in ("true", "1", "on", "yes") else "false"

        updates = {
            "level-name": name,
            "level-seed": seed,
            "gamemode": gamemode,
            "difficulty": difficulty,
            "max-players": max_players,
            "pvp": _bool("pvp", True),
            "show-coordinates": _bool("show-coordinates", False),
            "allow-cheats": _bool("allow-cheats", False),
            "force-gamemode": _bool("force-gamemode", False),
            "allow-list": "false",
        }
        if data.get("default_gamemode"):
            updates["gamemode"] = GAMEMODE_MAP.get(str(data["default_gamemode"]).lower(), gamemode)

        _stop_and_wait()
        _save_active_snapshot()

        world_path = WORLDS_DIR / name
        if world_path.exists():
            raise ValueError("ワールドフォルダが既に存在します")

        _apply_properties(updates)
        _ensure_open_join_settings()
        _start_and_wait()

        time.sleep(3)
        if not world_path.exists():
            raise RuntimeError("ワールドの生成に失敗しました")

        # Bedrock may reset server.properties on first world generation.
        _stop_and_wait()
        _ensure_open_join_settings()
        _start_and_wait()

        _ensure_death_notify_pack(name)

        profile = {
            "id": world_id,
            "folder": name,
            "display_name": name,
            "description": data.get("description", ""),
            "icon": "default",
            "created_at": _now_iso(),
            "last_played_at": _now_iso(),
            "gamemode": gamemode,
            "difficulty": difficulty,
            "seed": seed,
            "properties": {k: updates.get(k, "") for k in WORLD_PROPERTY_KEYS},
            "rules": {
                "spawn_protection": _bool("spawn_protection", True),
                "achievements": _bool("achievements", True),
                "daylight_cycle": _bool("daylight_cycle", True),
                "weather": _bool("weather", True),
                "immediate_respawn": _bool("immediate_respawn", False),
                "mob_spawn": _bool("mob_spawn", True),
                "mob_griefing": _bool("mob_griefing", True),
                "tnt": _bool("tnt", True),
                "fire_spread": _bool("fire_spread", True),
                "command_blocks_enabled": _bool("command_blocks_enabled", True),
            },
        }
        _save_profile(world_id, profile)

        reg = sync_registry()
        for wid, w in reg["worlds"].items():
            w["active"] = wid == world_id
        reg["active_id"] = world_id
        _save_registry(reg)
        _discord("world_create", world_name=name)
        _sync_global_addons()
        return True, world_id


def copy_world(world_id):
    with _lock:
        reg = sync_registry()
        if world_id not in reg["worlds"]:
            raise ValueError("ワールドが見つかりません")
        src = reg["worlds"][world_id]
        src_folder = src["folder"]
        new_name = _validate_level_name(f"{src.get('display_name', src_folder)}（コピー）")
        new_id = _slugify(new_name)
        suffix = 2
        base = new_id
        while (WORLDS_DIR / new_name).exists() or new_id in reg["worlds"]:
            new_name = _validate_level_name(f"{src.get('display_name', src_folder)}（コピー{suffix}）")
            new_id = f"{base}-{suffix}"
            suffix += 1

        _stop_and_wait()
        shutil.copytree(WORLDS_DIR / src_folder, WORLDS_DIR / new_name)

        profile = _load_profile(world_id)
        new_profile = dict(profile)
        new_profile.update({
            "id": new_id,
            "folder": new_name,
            "display_name": new_name,
            "created_at": _now_iso(),
            "last_played_at": None,
            "properties": dict(profile.get("properties", {})),
        })
        new_profile["properties"]["level-name"] = new_name
        _save_profile(new_id, new_profile)
        sync_registry()
        _sync_global_addons()
        return True, new_id


def delete_world(world_id, confirm_name):
    with _lock:
        reg = sync_registry()
        if world_id not in reg["worlds"]:
            raise ValueError("ワールドが見つかりません")
        entry = reg["worlds"][world_id]
        if entry.get("active"):
            raise ValueError("使用中のワールドは削除できません")
        if confirm_name != entry.get("display_name") and confirm_name != entry["folder"]:
            raise ValueError("ワールド名が一致しません")

        folder = entry["folder"]
        path = WORLDS_DIR / folder
        _stop_and_wait()
        if path.exists():
            shutil.rmtree(path)
        reg["worlds"].pop(world_id, None)
        _save_registry(reg)
        _profile_path(world_id).unlink(missing_ok=True)
        backup_dir = WORLD_BACKUP_DIR / world_id
        if backup_dir.exists():
            shutil.rmtree(backup_dir, ignore_errors=True)
        _start_and_wait()
        _discord("world_delete", world_name=entry.get("display_name", folder))
        return True, "削除しました"


def rename_world(world_id, new_name):
    with _lock:
        new_name = _validate_level_name(new_name)
        reg = sync_registry()
        if world_id not in reg["worlds"]:
            raise ValueError("ワールドが見つかりません")
        entry = reg["worlds"][world_id]
        old_folder = entry["folder"]
        if old_folder == new_name:
            return True, "変更なし"

        _stop_and_wait()
        src = WORLDS_DIR / old_folder
        dst = WORLDS_DIR / new_name
        if dst.exists():
            raise ValueError("同名のワールドが既にあります")
        if src.exists():
            src.rename(dst)

        profile = _load_profile(world_id)
        profile["display_name"] = new_name
        profile["folder"] = new_name
        if "properties" in profile:
            profile["properties"]["level-name"] = new_name
        _save_profile(world_id, profile)

        if entry.get("active"):
            _apply_properties({"level-name": new_name})

        entry["folder"] = new_name
        entry["display_name"] = new_name
        reg["worlds"][world_id] = entry
        _save_registry(reg)
        _start_and_wait()
        return True, "名前を変更しました"


def update_world_meta(world_id, data):
    reg = sync_registry()
    if world_id not in reg["worlds"]:
        raise ValueError("ワールドが見つかりません")
    profile = _load_profile(world_id)
    if "description" in data:
        profile["description"] = str(data["description"])[:500]
    if "display_name" in data and not reg["worlds"][world_id].get("active"):
        profile["display_name"] = str(data["display_name"])[:64]
    if "icon" in data:
        icon = str(data["icon"]).strip()[:8]
        profile["icon"] = icon or "default"
    _save_profile(world_id, profile)
    if world_id in reg["worlds"]:
        if "description" in data:
            reg["worlds"][world_id]["description"] = profile["description"]
        if "icon" in data:
            reg["worlds"][world_id]["icon"] = profile["icon"]
        _save_registry(reg)
    sync_registry()
    return True, "保存しました"


def create_world_backup(world_id):
    with _lock:
        reg = sync_registry()
        if world_id not in reg["worlds"]:
            raise ValueError("ワールドが見つかりません")
        folder = reg["worlds"][world_id]["folder"]
        world_path = WORLDS_DIR / folder
        if not world_path.exists():
            raise ValueError("ワールドフォルダが見つかりません")

        backup_id = _now_id()
        dest_dir = WORLD_BACKUP_DIR / world_id
        dest_dir.mkdir(parents=True, exist_ok=True)
        archive = dest_dir / f"{backup_id}.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(world_path, arcname=folder)
        size = archive.stat().st_size
        meta = {
            "id": backup_id,
            "world_id": world_id,
            "created": _now_iso(),
            "created_label": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "size": size,
            "size_label": _format_size(size),
        }
        _write_json(dest_dir / f"{backup_id}.meta.json", meta)
        _prune_world_backups(world_id)
        _discord("backup_success", size=meta.get("size_label", "-"))
        return backup_id, meta


def _prune_world_backups(world_id):
    dest_dir = WORLD_BACKUP_DIR / world_id
    if not dest_dir.exists():
        return
    archives = sorted(dest_dir.glob("*.tar.gz"), key=lambda p: p.name, reverse=True)
    for old in archives[MAX_WORLD_BACKUPS:]:
        bid = old.stem
        old.unlink(missing_ok=True)
        (dest_dir / f"{bid}.meta.json").unlink(missing_ok=True)


def list_world_backups(world_id):
    dest_dir = WORLD_BACKUP_DIR / world_id
    if not dest_dir.exists():
        return []
    backups = []
    for meta_path in sorted(dest_dir.glob("*.meta.json"), key=lambda p: p.name, reverse=True):
        meta = _read_json(meta_path, {})
        bid = meta.get("id") or meta_path.stem.replace(".meta", "")
        if (dest_dir / f"{bid}.tar.gz").exists():
            backups.append(meta)
    return backups[:MAX_WORLD_BACKUPS]


def restore_world_backup(world_id, backup_id):
    with _lock:
        if not re.fullmatch(r"\d{8}-\d{6}", backup_id):
            raise ValueError("無効なバックアップID")
        reg = sync_registry()
        if world_id not in reg["worlds"]:
            raise ValueError("ワールドが見つかりません")
        folder = reg["worlds"][world_id]["folder"]
        archive = WORLD_BACKUP_DIR / world_id / f"{backup_id}.tar.gz"
        if not archive.exists():
            raise FileNotFoundError("バックアップが見つかりません")

        _stop_and_wait()
        world_path = WORLDS_DIR / folder
        if world_path.exists():
            shutil.rmtree(world_path)
        with tarfile.open(archive, "r:gz") as tar:
            tar.extractall(path=WORLDS_DIR)
        _start_and_wait()
        sync_registry()
        return True, "復元しました"


def delete_world_backup(world_id, backup_id):
    if not re.fullmatch(r"\d{8}-\d{6}", backup_id):
        raise ValueError("無効なバックアップID")
    base = WORLD_BACKUP_DIR / world_id
    (base / f"{backup_id}.tar.gz").unlink(missing_ok=True)
    (base / f"{backup_id}.meta.json").unlink(missing_ok=True)
    return True, "削除しました"


def export_world_path(world_id):
    reg = sync_registry()
    if world_id not in reg["worlds"]:
        raise ValueError("ワールドが見つかりません")
    entry = reg["worlds"][world_id]
    folder = entry["folder"]
    world_path = WORLDS_DIR / folder
    if not world_path.exists():
        raise ValueError("ワールドフォルダが見つかりません")

    display = entry.get("display_name") or folder
    safe = re.sub(r'[\\/:*?"<>|]', "", display).strip() or folder
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = WORK_DIR / f"{_slugify(safe)}.mcworld"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(world_path):
            for fname in files:
                full = Path(root) / fname
                arc = str(full.relative_to(world_path))
                zf.write(full, arc)
    return zip_path


def import_world(upload_path, original_name):
    with _lock:
        name = Path(original_name or "world").stem
        if name.endswith("-export"):
            name = name[:-7]
        name = _validate_level_name(name)

        reg = _load_registry()
        world_id = _slugify(name)
        if (WORLDS_DIR / name).exists():
            name = _validate_level_name(f"{name}（インポート）")
            world_id = _slugify(name)

        _stop_and_wait()
        tmp_extract = WORK_DIR / f"import-{_now_id()}"
        tmp_extract.mkdir(parents=True, exist_ok=True)
        try:
            upload = Path(upload_path)
            lower = (original_name or upload.name or "").lower()
            if not (lower.endswith(".zip") or lower.endswith(".mcworld")):
                raise ValueError("zip または mcworld ファイルを選択してください")

            with zipfile.ZipFile(upload, "r") as zf:
                zf.extractall(tmp_extract)

            world_root = _find_world_data_dir(tmp_extract)
            display_name = _read_levelname(world_root) or name
            display_name = display_name[:64]

            dest = WORLDS_DIR / name
            if dest.exists():
                shutil.rmtree(dest)
            shutil.move(str(world_root), str(dest))
            if not (dest / "level.dat").is_file():
                raise ValueError("ワールドデータの展開に失敗しました")
            _ensure_death_notify_pack(name)
        finally:
            shutil.rmtree(tmp_extract, ignore_errors=True)

        profile = {
            "id": world_id,
            "folder": name,
            "display_name": display_name,
            "created_at": _now_iso(),
            "last_played_at": _now_iso(),
            "properties": _snapshot_properties(name),
        }
        _save_profile(world_id, profile)
        sync_registry()
        _sync_global_addons()
        _start_and_wait()
        return True, world_id


def get_dashboard_world():
    players_online = 0
    players_max = 10
    active_folder = ""
    try:
        from app.discord_manager import get_online_player_count
        players_online = get_online_player_count()
        _, props = read_properties()
        players_max = int(props.get("max-players", "10"))
        active_folder = props.get("level-name", "")
    except Exception:
        active_folder = get_active_world_folder()

    reg = sync_registry()
    current = None
    for entry in reg.get("worlds", {}).values():
        if entry.get("active"):
            current = entry
            break
    if not current:
        return {
            "display_name": active_folder or "-",
            "gamemode": "-",
            "difficulty": "-",
            "players_online": players_online,
            "players_max": players_max,
            "icon": "default",
        }
    return {
        "display_name": current.get("display_name") or current.get("folder") or active_folder,
        "gamemode": current.get("gamemode", "-"),
        "difficulty": current.get("difficulty", "-"),
        "players_online": players_online,
        "players_max": players_max,
        "icon": current.get("icon", "default"),
        "active": True,
    }
