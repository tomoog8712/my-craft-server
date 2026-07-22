"""server.properties parser/writer with comment preservation and dynamic schema."""

import re
from pathlib import Path

PROPERTIES_PATH = Path("/opt/minecraft/server.properties")

# Server-wide property keys (per-world keys live on the world settings screen).
UI_SECTIONS = [
    {
        "id": "server",
        "label": {"ja": "サーバー", "en": "Server"},
        "source": "server.properties",
        "keys": [
            "server-name",
        ],
    },
]

UI_VISIBLE_KEYS = {key for section in UI_SECTIONS for key in section["keys"]}
SERVER_UI_VISIBLE_KEYS = UI_VISIBLE_KEYS

WORLD_PROPERTY_UI_KEYS = [
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

WORLD_RULE_KEYS = [
    "spawn_protection",
    "achievements",
    "daylight_cycle",
    "weather",
    "immediate_respawn",
    "mob_spawn",
    "mob_griefing",
    "tnt",
    "fire_spread",
    "command_blocks_enabled",
]

WORLD_RULE_LABELS = {
    "spawn_protection": "初期スポーン保護",
    "achievements": "実績",
    "daylight_cycle": "昼夜サイクル",
    "weather": "天候変化",
    "immediate_respawn": "即時リスポーン",
    "mob_spawn": "Mobスポーン",
    "mob_griefing": "Mobによる破壊",
    "tnt": "TNT爆発",
    "fire_spread": "火の延焼",
    "command_blocks_enabled": "コマンドブロック",
}

FUTURE_EXTENSIONS = [
    {
        "id": "allowlist",
        "label": {"ja": "参加許可リスト", "en": "Allowlist"},
        "source": "allowlist.json",
        "enabled": False,
    },
    {
        "id": "permissions",
        "label": {"ja": "権限設定", "en": "Permissions"},
        "source": "permissions.json",
        "enabled": False,
    },
    {
        "id": "discord",
        "label": {"ja": "Discord通知", "en": "Discord"},
        "source": "discord",
        "enabled": False,
    },
    {
        "id": "update",
        "label": {"ja": "アップデート", "en": "Updates"},
        "source": "update",
        "enabled": False,
        "route": "/update",
    },
]

PRIORITY_KEYS = list(UI_VISIBLE_KEYS)

FIELD_LABELS = {
    "server-name": {"ja": "サーバー名", "en": "Server Name"},
    "max-players": {"ja": "最大人数", "en": "Max Players"},
    "difficulty": {"ja": "難易度", "en": "Difficulty"},
    "gamemode": {"ja": "ゲームモード", "en": "Game Mode"},
    "pvp": {"ja": "PvP", "en": "PvP"},
    "allow-cheats": {"ja": "コマンド許可", "en": "Allow Commands"},
    "show-coordinates": {"ja": "座標表示", "en": "Show Coordinates"},
    "allow-list": {"ja": "ホワイトリスト", "en": "Whitelist"},
    "online-mode": {"ja": "オンライン認証", "en": "Online Mode"},
    "view-distance": {"ja": "ビュー距離", "en": "View Distance"},
    "tick-distance": {"ja": "Tick距離", "en": "Tick Distance"},
    "player-idle-timeout": {"ja": "プレイヤーアイドル時間（分）", "en": "Player Idle Timeout (min)"},
    "force-gamemode": {"ja": "ゲームモード強制", "en": "Force Gamemode"},
    "server-port": {"ja": "サーバーポート", "en": "Server Port"},
    "level-name": {"ja": "ワールド名", "en": "Level Name"},
    "level-seed": {"ja": "ワールドシード", "en": "Level Seed"},
    "default-player-permission-level": {"ja": "デフォルト権限", "en": "Default Permission"},
    "texturepack-required": {"ja": "テクスチャ必須", "en": "Texture Pack Required"},
    "compression-threshold": {"ja": "圧縮レベル", "en": "Compression Threshold"},
    "compression-algorithm": {"ja": "圧縮アルゴリズム", "en": "Compression Algorithm"},
    "enable-lan-visibility": {"ja": "LANブロードキャスト", "en": "LAN Broadcast"},
    "content-log-file-enabled": {"ja": "コンテンツログ", "en": "Content Log"},
    "content-log-level": {"ja": "ログレベル", "en": "Log Level"},
    "server-portv6": {"ja": "IPv6ポート", "en": "IPv6 Port"},
}

FIELD_WIDGETS = {
    "server-name": {"type": "text"},
    "max-players": {"type": "stepper", "min": 1, "max": 200},
    "view-distance": {"type": "slider", "min": 5, "max": 96},
    "tick-distance": {"type": "slider", "min": 4, "max": 12},
    "player-idle-timeout": {"type": "number", "min": 0, "max": 9999},
    "online-mode": {"warn_off": True},
    "server-port": {"type": "number", "min": 1, "max": 65535},
    "server-portv6": {"type": "number", "min": 1, "max": 65535},
    "max-threads": {"type": "number", "min": 0, "max": 256},
    "compression-threshold": {"type": "number", "min": 0, "max": 65535},
}

BOOL_VALUES = {"true", "false"}
ENUM_OPTION_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]*$")


def _normalize_enum_options(options):
    if not options:
        return None
    cleaned = []
    for opt in options:
        token = str(opt).strip()
        if ENUM_OPTION_RE.fullmatch(token):
            cleaned.append(token)
    if len(cleaned) < 2:
        return None
    return list(dict.fromkeys(cleaned))


def _parse_bool(value):
    return str(value).lower() in ("true", "1", "yes", "on")


def _to_bool_str(value):
    return "true" if _parse_bool(value) else "false"


def _format_key(key):
    return key.replace("-", " ").title()


def _extract_allowed_values(comments):
    for comment in reversed(comments):
        lower = comment.lower()
        if "allowed values" not in lower:
            continue

        quoted = re.findall(r'"([^"]+)"', comment)
        if quoted:
            normalized = _normalize_enum_options(quoted)
            if normalized:
                return normalized

        if "true" in lower and "false" in lower:
            return ["true", "false"]

        if re.search(r"\[\d", comment):
            return None

        if re.search(r"\bor\b", comment, re.I) and '"' in comment:
            or_parts = re.split(r"\bor\b", comment, flags=re.I)
            options = []
            for part in or_parts:
                part = re.sub(r"^.*?:\s*", "", part)
                for token in re.findall(r'"([^"]+)"', part):
                    options.append(token)
                part = part.strip().strip('"').strip("'")
                if part and ENUM_OPTION_RE.fullmatch(part):
                    options.append(part)
            normalized = _normalize_enum_options(options)
            if normalized:
                return normalized

    enum_candidates = []
    for comment in comments:
        if "allowed values" in comment.lower():
            continue
        for token in re.findall(r'"([a-z][a-z0-9-]*)"', comment, re.I):
            if token.lower() not in BOOL_VALUES:
                enum_candidates.append(token)
    normalized = _normalize_enum_options(enum_candidates)
    if normalized:
        return normalized

    return None


def _extract_numeric_range(comments):
    for comment in reversed(comments):
        match = re.search(r"\[(\d+(?:\.\d+)?),\s*(\d+(?:\.\d+)?)\]", comment)
        if match:
            return float(match.group(1)), float(match.group(2))
        if "positive integer" in comment.lower() and "equal to" in comment.lower():
            num_match = re.search(r"equal to (\d+)", comment.lower())
            if num_match:
                return int(num_match.group(1)), 96
    return None, None


def _infer_field_type(key, value, comments, options):
    widget = FIELD_WIDGETS.get(key, {})
    if widget.get("type"):
        return widget["type"]

    if options:
        normalized = {opt.lower() for opt in options}
        if normalized <= BOOL_VALUES or normalized == {"true", "false"}:
            return "boolean"
        return "enum"

    if str(value).lower() in BOOL_VALUES:
        return "boolean"

    if re.fullmatch(r"-?\d+", value or ""):
        min_val, max_val = _extract_numeric_range(comments)
        if min_val is not None and max_val is not None and (max_val - min_val) <= 200:
            return "slider"
        return "number"

    if re.fullmatch(r"-?\d+\.\d+", value or ""):
        return "number"

    return "text"


def parse_properties_file():
    """Parse server.properties into ordered entries with comments."""
    if not PROPERTIES_PATH.exists():
        return [], []

    lines = PROPERTIES_PATH.read_text(encoding="utf-8").splitlines()
    entries = []
    pending_before = []
    i = 0

    while i < len(lines):
        stripped = lines[i].strip()
        if not stripped:
            pending_before = []
            i += 1
            continue
        if stripped.startswith("#"):
            pending_before.append(stripped[1:].strip())
            i += 1
            continue
        if "=" not in stripped:
            pending_before = []
            i += 1
            continue

        key, value = stripped.split("=", 1)
        key = key.strip()
        comments = list(pending_before)
        pending_before = []
        i += 1

        while i < len(lines):
            nxt = lines[i].strip()
            if not nxt:
                break
            if nxt.startswith("#"):
                comments.append(nxt[1:].strip())
                i += 1
                continue
            break

        entries.append({
            "key": key,
            "value": value.strip(),
            "comments": comments,
        })

    return entries, [entry["key"] for entry in entries]


def read_properties():
    """Return (raw_lines, key_values dict)."""
    entries, _ = parse_properties_file()
    if not entries:
        return [], {}

    lines = PROPERTIES_PATH.read_text(encoding="utf-8").splitlines()
    values = {entry["key"]: entry["value"] for entry in entries}
    return lines, values


def _build_field_schema(entry):
    key = entry["key"]
    value = entry["value"]
    comments = entry["comments"]
    options = _extract_allowed_values(comments)
    field_type = _infer_field_type(key, value, comments, options)
    widget = FIELD_WIDGETS.get(key, {})
    min_val, max_val = _extract_numeric_range(comments)

    if widget.get("min") is not None:
        min_val = widget["min"]
    if widget.get("max") is not None:
        max_val = widget["max"]

    description = comments[0] if comments else ""
    labels = FIELD_LABELS.get(key, {"ja": _format_key(key), "en": _format_key(key)})

    if field_type == "boolean":
        options = ["true", "false"]

    return {
        "key": key,
        "value": value,
        "type": field_type,
        "label": labels,
        "description": description,
        "options": options,
        "min": min_val,
        "max": max_val,
        "warn_off": bool(widget.get("warn_off")),
        "priority": key in PRIORITY_KEYS,
    }


def build_settings_response():
    entries, _ = parse_properties_file()
    fields_by_key = {_build_field_schema(entry)["key"]: _build_field_schema(entry) for entry in entries}

    sections = []
    for section_def in UI_SECTIONS:
        fields = []
        for key in section_def["keys"]:
            field = fields_by_key.get(key)
            if not field:
                continue
            field = dict(field)
            field["section"] = section_def["id"]
            fields.append(field)
        if fields:
            sections.append({
                "id": section_def["id"],
                "label": section_def["label"],
                "source": section_def["source"],
                "fields": fields,
            })

    flat_fields = []
    for section in sections:
        flat_fields.extend(section["fields"])

    return {
        "sections": sections,
        "fields": flat_fields,
        "extensions": FUTURE_EXTENSIONS,
        "editable_keys": sorted(UI_VISIBLE_KEYS),
    }


def get_visible_fields_by_key():
    response = build_settings_response()
    result = {}
    for section in response["sections"]:
        for field in section["fields"]:
            result[field["key"]] = field
    return result


def _serialize_value(field, raw_value):
    field_type = field["type"]
    key = field["key"]

    if field_type == "boolean":
        return _to_bool_str(raw_value)

    if field_type in ("stepper", "slider", "number"):
        num = float(raw_value)
        if field.get("min") is not None:
            num = max(float(field["min"]), num)
        if field.get("max") is not None:
            num = min(float(field["max"]), num)
        if field_type in ("stepper", "slider") or key in (
            "max-players",
            "view-distance",
            "tick-distance",
            "player-idle-timeout",
            "server-port",
            "server-portv6",
            "max-threads",
            "compression-threshold",
        ):
            if float(num).is_integer():
                return str(int(num))
        return str(num)

    if field_type == "enum":
        options = field.get("options") or []
        val = str(raw_value)
        for opt in options:
            if opt.lower() == val.lower():
                return opt
        return val

    return str(raw_value).strip()


def settings_to_updates(data, allowed_keys, fields_by_key):
    props = data.get("properties")
    if not isinstance(props, dict):
        raise ValueError("Invalid properties payload")

    updates = {}
    for key, raw_value in props.items():
        if key not in UI_VISIBLE_KEYS:
            continue
        if key not in allowed_keys:
            continue
        field = fields_by_key.get(key)
        if not field:
            continue
        updates[key] = _serialize_value(field, raw_value)
    return updates


def write_properties(updates):
    """Update keys in server.properties, preserving comments."""
    lines, values = read_properties()
    if not lines:
        return False

    allowed_keys = set(values.keys())
    updated_keys = set()
    new_lines = []

    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key, _, _ = stripped.partition("=")
            key = key.strip()
            if key in allowed_keys and key in updates:
                new_lines.append(f"{key}={updates[key]}")
                updated_keys.add(key)
                continue
        new_lines.append(line)

    for key, val in updates.items():
        if key in allowed_keys and key not in updated_keys:
            new_lines.append(f"{key}={val}")

    content = "\n".join(new_lines)
    if not content.endswith("\n"):
        content += "\n"

    PROPERTIES_PATH.write_text(content, encoding="utf-8")
    return True
