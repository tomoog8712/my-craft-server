"""Discord webhook notifications for My Craft Server."""

import fcntl
import json
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

CONFIG_FILE = Path("/etc/appliance/config.json")
DATA_DIR = Path("/opt/appliance/data")
DISCORD_FILE = DATA_DIR / "discord.json"
HISTORY_FILE = DATA_DIR / "discord_history.json"
MONITOR_FILE = DATA_DIR / "discord_monitor.json"
MONITOR_LOCK_FILE = DATA_DIR / "discord_monitor.lock"
CONFIG_WRITE_SCRIPT = "/opt/appliance/bin/discord-config-write.sh"

POLL_INTERVAL_SEC = 5
POLL_OVERLAP_SEC = 5
NOTIFY_DEDUP_SEC = 45

DEFAULT_EVENTS = {
    "server_start": True,
    "server_stop": True,
    "player_join": True,
    "player_leave": True,
    "player_death": True,
    "backup_success": True,
    "backup_fail": True,
    "update_start": True,
    "update_complete": True,
    "update_fail": True,
    "world_switch": True,
    "world_create": True,
    "world_delete": True,
    "system_error": True,
    "ssd_warning": True,
    "memory_warning": True,
    "cpu_high": True,
}

EVENT_LABELS = {
    "server_start": "サーバー起動",
    "server_stop": "サーバー停止",
    "player_join": "プレイヤー参加",
    "player_leave": "プレイヤー退出",
    "player_death": "プレイヤー死亡",
    "backup_success": "バックアップ成功",
    "backup_fail": "バックアップ失敗",
    "update_start": "アップデート開始",
    "update_complete": "アップデート完了",
    "update_fail": "アップデート失敗",
    "world_switch": "ワールド切替",
    "world_create": "ワールド作成",
    "world_delete": "ワールド削除",
    "system_error": "システムエラー",
    "ssd_warning": "SSD容量警告",
    "memory_warning": "メモリ不足",
    "cpu_high": "CPU高負荷",
}

COLORS = {
    "green": 0x2D6A4F,
    "red": 0xD00000,
    "blue": 0x1D6FD8,
    "orange": 0xE85D04,
    "yellow": 0xF4A100,
    "gray": 0x6C757D,
}

_lock = threading.Lock()
_monitor_started = False
_monitor_lock_fp = None
_notify_cache = {}

JOIN_RE = re.compile(r"Player connected:\s*([^,]+),\s*xuid:\s*(\d+)")
JOIN_NAME_RE = re.compile(r"Player connected:\s*([^,]+)")
SPAWNED_RE = re.compile(r"Player Spawned:\s*(\S+)")
LEAVE_RE = re.compile(r"Player disconnected:\s*([^,]+)")
MHDEATH_RE = re.compile(r"MHDEATH:([^:\s]+):(.+)")
DEATH_RE = re.compile(
    r"(?:death|died|was slain|was blown up|was killed|fell|drowned|burned)",
    re.IGNORECASE,
)
SERVER_STARTED_RE = re.compile(r"Server started\.")
SERVER_STOP_RE = re.compile(r"Server stop requested\.")
BEDROCK_START_TS_RE = re.compile(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _now_label():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _now_poll_ts():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _player_name(raw):
    return (raw or "").strip()


def _journal_since(last_poll_at):
    if not last_poll_at:
        return "2 min ago"
    try:
        dt = datetime.strptime(last_poll_at, "%Y-%m-%d %H:%M:%S")
        dt -= timedelta(seconds=POLL_OVERLAP_SEC)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return "2 min ago"


def _notify_deduped(event, **kwargs):
    player = kwargs.get("player", "")
    key = (event, player)
    now = time.time()
    if now - _notify_cache.get(key, 0) < NOTIFY_DEDUP_SEC:
        return False, "skipped"
    ok, msg = notify(event, **kwargs)
    if ok:
        _notify_cache[key] = now
    return ok, msg


def _read_json(path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default if default is not None else {}


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _run(cmd, timeout=30):
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        return 1, "", str(exc)


def _read_config():
    return _read_json(CONFIG_FILE, {})


def _mask_webhook(url):
    if not url:
        return ""
    if len(url) <= 16:
        return "*" * len(url)
    return url[:8] + "*" * 12 + url[-4:]


def _get_discord_section():
    discord = _read_json(DISCORD_FILE, {})
    if not discord:
        config = _read_config()
        discord = config.get("discord", {})
    events = dict(DEFAULT_EVENTS)
    events.update(discord.get("events", {}))
    return {
        "webhook_url": discord.get("webhook_url", ""),
        "events": events,
    }


def _sync_config_json(discord):
    try:
        config = _read_config()
        config["discord"] = discord
        tmp = DATA_DIR / "config-write-tmp.json"
        _write_json(tmp, config)
        code, _, _ = _run(["sudo", "-n", CONFIG_WRITE_SCRIPT, str(tmp)])
        return code == 0
    except OSError:
        return False


def _save_discord_section(webhook_url=None, events=None):
    current = _get_discord_section()
    discord = {
        "webhook_url": current.get("webhook_url", ""),
        "events": dict(current.get("events", DEFAULT_EVENTS)),
    }
    if webhook_url is not None:
        discord["webhook_url"] = webhook_url.strip()
    if events is not None:
        merged = dict(DEFAULT_EVENTS)
        merged.update(events)
        discord["events"] = merged
    _write_json(DISCORD_FILE, discord)
    _sync_config_json(discord)
    return discord


def get_discord_status():
    section = _get_discord_section()
    url = section.get("webhook_url", "")
    configured = bool(url)
    return {
        "configured": configured,
        "status": "接続済み" if configured else "未設定",
        "status_class": "on" if configured else "off",
        "webhook_masked": _mask_webhook(url) if url else "",
        "events": section.get("events", DEFAULT_EVENTS),
        "history": list_history(),
    }


def get_discord_dashboard_status():
    section = _get_discord_section()
    url = section.get("webhook_url", "")
    configured = bool(url)
    return {
        "configured": configured,
        "status": "接続済み" if configured else "未設定",
        "status_class": "on" if configured else "off",
    }


def list_history():
    data = _read_json(HISTORY_FILE, {"items": []})
    return data.get("items", [])[:20]


def _append_history(event, title, success=True, detail=""):
    with _lock:
        data = _read_json(HISTORY_FILE, {"items": []})
        items = data.get("items", [])
        items.insert(0, {
            "time": _now_label(),
            "event": event,
            "title": title,
            "success": success,
            "detail": detail,
        })
        data["items"] = items[:20]
        _write_json(HISTORY_FILE, data)


def _get_world_context():
    try:
        from app.settings_manager import read_properties
        _, props = read_properties()
        return {
            "world_name": props.get("level-name", "-"),
            "players_online": get_online_player_count(),
            "players_max": int(props.get("max-players", "10")),
        }
    except Exception:
        return {"world_name": "-", "players_online": 0, "players_max": 10}


def _build_embed(title, description="", fields=None, color="green"):
    embed = {
        "title": title,
        "color": COLORS.get(color, COLORS["green"]),
        "footer": {"text": "My Craft Server"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if description:
        embed["description"] = description
    if fields:
        embed["fields"] = [
            {"name": f["name"], "value": str(f["value"]), "inline": bool(f.get("inline", True))}
            for f in fields
        ]
    return embed


def _send_webhook(embed, event="test", title="通知"):
    section = _get_discord_section()
    url = section.get("webhook_url", "").strip()
    if not url:
        return False, "Webhook URLが未設定です"
    payload = json.dumps({"embeds": [embed]}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "MyCraftServer/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if 200 <= resp.status < 300:
                _append_history(event, title, True)
                return True, "送信しました"
            body = resp.read().decode("utf-8", errors="replace")
            _append_history(event, title, False, body[:120])
            return False, f"Discordエラー ({resp.status})"
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        _append_history(event, title, False, body[:120])
        return False, f"Discordエラー ({exc.code})"
    except Exception as exc:
        _append_history(event, title, False, str(exc))
        return False, str(exc)


def notify(event, **kwargs):
    section = _get_discord_section()
    if not section.get("webhook_url"):
        return False, "未設定"
    events = section.get("events", DEFAULT_EVENTS)
    if not events.get(event, True):
        return False, "通知オフ"

    ctx = _get_world_context()
    fields = []
    title = ""
    color = "green"

    if event == "server_start":
        title = "🟢 サーバー起動"
        color = "green"
        fields = [{"name": "ワールド", "value": ctx["world_name"]}]
    elif event == "server_stop":
        title = "🔴 サーバー停止"
        color = "red"
    elif event == "player_join":
        player = kwargs.get("player", "Unknown")
        online = kwargs.get("players_online", ctx["players_online"])
        title = "🎮 プレイヤー参加"
        fields = [
            {"name": "プレイヤー", "value": player},
            {"name": "現在人数", "value": f"{online} / {ctx['players_max']}"},
            {"name": "ワールド", "value": ctx["world_name"]},
        ]
    elif event == "player_leave":
        player = kwargs.get("player", "Unknown")
        online = kwargs.get("players_online", ctx["players_online"])
        title = "👋 プレイヤー退出"
        fields = [
            {"name": "プレイヤー", "value": player},
            {"name": "現在人数", "value": f"{online} / {ctx['players_max']}"},
        ]
    elif event == "player_death":
        player = kwargs.get("player", "Unknown")
        detail = kwargs.get("detail", "died")
        title = "💀 プレイヤー死亡"
        fields = [{"name": "詳細", "value": f"{player} {detail}"}]
        color = "orange"
    elif event == "backup_success":
        title = "💾 バックアップ完了"
        fields = [{"name": "サイズ", "value": kwargs.get("size", "-")}]
    elif event == "backup_fail":
        title = "💾 バックアップ失敗"
        color = "red"
        fields = [{"name": "詳細", "value": kwargs.get("detail", "-")}]
    elif event == "update_start":
        title = "⬆ アップデート開始"
        fields = [{"name": "バージョン", "value": kwargs.get("version", "-")}]
        color = "blue"
    elif event == "update_complete":
        title = "⬆ 更新完了"
        fields = [
            {"name": "変更", "value": f"{kwargs.get('from_version', '-')} → {kwargs.get('to_version', '-')}"},
        ]
        color = "green"
    elif event == "update_fail":
        title = "⬆ アップデート失敗"
        color = "red"
        fields = [{"name": "詳細", "value": kwargs.get("detail", "-")}]
    elif event == "world_switch":
        title = "🌍 ワールド切替"
        fields = [{"name": "変更", "value": f"{kwargs.get('from_world', '-')} → {kwargs.get('to_world', '-')}"}]
        color = "blue"
    elif event == "world_create":
        title = "🌍 ワールド作成"
        fields = [{"name": "ワールド", "value": kwargs.get("world_name", "-")}]
    elif event == "world_delete":
        title = "🌍 ワールド削除"
        color = "orange"
        fields = [{"name": "ワールド", "value": kwargs.get("world_name", "-")}]
    elif event == "system_error":
        title = "⚠ システムエラー"
        color = "red"
        fields = [{"name": "詳細", "value": kwargs.get("detail", "-")}]
    elif event == "ssd_warning":
        title = "⚠ SSD残り容量"
        color = "orange"
        fields = [{"name": "残り", "value": kwargs.get("detail", "-")}]
    elif event == "memory_warning":
        title = "⚠ メモリ不足"
        color = "orange"
        fields = [{"name": "詳細", "value": kwargs.get("detail", "-")}]
    elif event == "cpu_high":
        title = "⚠ CPU高負荷"
        color = "orange"
        fields = [{"name": "詳細", "value": kwargs.get("detail", "-")}]
    else:
        title = kwargs.get("title", "通知")
        if kwargs.get("detail"):
            fields = [{"name": "詳細", "value": kwargs["detail"]}]

    embed = _build_embed(title, fields=fields, color=color)
    ok, msg = _send_webhook(embed, event=event, title=title)
    return ok, msg


def send_test_notification():
    embed = _build_embed(
        "🟢 Discord通知は正常です。",
        description="My Craft Server",
        color="green",
    )
    return _send_webhook(embed, event="test", title="接続テスト")


def save_webhook_url(url):
    url = (url or "").strip()
    if url and not url.startswith("https://discord.com/api/webhooks/"):
        raise ValueError("Discord Webhook URLの形式が正しくありません")
    _save_discord_section(webhook_url=url)
    return True, "保存しました"


def save_event_settings(events):
    clean = {}
    for key in DEFAULT_EVENTS:
        if key in events:
            clean[key] = bool(events[key])
    _save_discord_section(events=clean)
    return True, "保存しました"


def _load_monitor_state():
    return _read_json(MONITOR_FILE, {
        "last_poll_at": "",
        "connected_players": [],
        "alerts": {},
    })


def _save_monitor_state(state):
    _write_json(MONITOR_FILE, state)


def _journal_lines(since):
    code, out, _ = _run(
        ["journalctl", "-u", "bedrock", "--since", since, "--no-pager", "-o", "cat"],
        timeout=15,
    )
    if code != 0:
        return []
    return [ln for ln in out.splitlines() if ln.strip()]


def _track_player_registry(line_or_name, xuid=None):
    try:
        from app.player_manager import track_player_join, track_player_from_log_line
        if isinstance(line_or_name, str) and "Player connected:" in line_or_name:
            track_player_from_log_line(line_or_name)
        else:
            track_player_join(line_or_name, xuid)
    except Exception:
        pass


def _build_player_set(lines):
    players = set()
    for line in lines:
        if SERVER_STARTED_RE.search(line):
            players.clear()
            continue
        if SERVER_STOP_RE.search(line):
            players.clear()
            continue
        m = JOIN_RE.search(line)
        if m:
            name = _player_name(m.group(1))
            players.add(name)
            _track_player_registry(line)
            continue
        m = JOIN_NAME_RE.search(line)
        if m:
            name = _player_name(m.group(1))
            players.add(name)
            _track_player_registry(line)
            continue
        m = LEAVE_RE.search(line)
        if m:
            players.discard(_player_name(m.group(1)))
    return players


def get_online_players():
    now = time.time()
    cached = getattr(get_online_players, "_cache", None)
    if cached and now - cached["at"] < 15:
        return list(cached["players"])
    lines = _journal_lines("2 hours ago")
    players = sorted(_build_player_set(lines))
    get_online_players._cache = {"players": players, "at": now}
    return players


def get_online_player_count():
    return len(get_online_players())


def get_bedrock_uptime_label():
    now = time.time()
    cached = getattr(get_bedrock_uptime_label, "_cache", None)
    if cached and now - cached["at"] < 30:
        return cached["label"]
    code, out, _ = _run(
        ["journalctl", "-u", "bedrock", "-n", "400", "--no-pager", "-o", "short-iso"],
        timeout=10,
    )
    if code != 0:
        label = "-"
        get_bedrock_uptime_label._cache = {"label": label, "at": now}
        return label
    last_start = None
    for line in out.splitlines():
        if "Server started." not in line:
            continue
        m = BEDROCK_START_TS_RE.search(line)
        if m:
            last_start = m.group(1)
    if not last_start:
        label = "-"
        get_bedrock_uptime_label._cache = {"label": label, "at": now}
        return label
    try:
        started = datetime.strptime(last_start, "%Y-%m-%d %H:%M:%S")
        delta = datetime.now() - started
        seconds = int(delta.total_seconds())
        if seconds < 60:
            label = "1分未満"
        else:
            minutes = seconds // 60
            if minutes < 60:
                label = f"{minutes}分"
            else:
                hours = minutes // 60
                rem = minutes % 60
                label = f"{hours}時間{rem}分" if rem else f"{hours}時間"
    except ValueError:
        label = "-"
    get_bedrock_uptime_label._cache = {"label": label, "at": now}
    return label


def _poll_journal_events():
    state = _load_monitor_state()
    poll_started_at = _now_poll_ts()
    prev_known = set(state.get("connected_players", []))

    if not state.get("last_poll_at"):
        reconciled = _build_player_set(_journal_lines("12 hours ago"))
        state["connected_players"] = sorted(reconciled)
        state["last_poll_at"] = poll_started_at
        _save_monitor_state(state)
        return

    since = _journal_since(state.get("last_poll_at"))
    lines = _journal_lines(since)
    players = set(prev_known)
    notified_joins = set()
    notified_leaves = set()

    for line in lines:
        m = JOIN_RE.search(line)
        if m:
            name = _player_name(m.group(1))
            if name and name not in players:
                players.add(name)
                notified_joins.add(name)
                try:
                    from app.world_manager import track_player_join
                    track_player_join(name)
                except Exception:
                    pass
                _track_player_registry(line)
                _notify_deduped("player_join", player=name, players_online=len(players))
            continue
        m = JOIN_NAME_RE.search(line)
        if m:
            name = _player_name(m.group(1))
            if name and name not in players:
                players.add(name)
                notified_joins.add(name)
                try:
                    from app.world_manager import track_player_join
                    track_player_join(name)
                except Exception:
                    pass
                _track_player_registry(line)
                _notify_deduped("player_join", player=name, players_online=len(players))
            continue
        m = SPAWNED_RE.search(line)
        if m:
            name = _player_name(m.group(1))
            if name:
                try:
                    from app.player_manager import kick_if_banned
                    kick_if_banned(name)
                except Exception:
                    pass
            continue
        m = LEAVE_RE.search(line)
        if m:
            name = _player_name(m.group(1))
            if name and name in players:
                players.discard(name)
                notified_leaves.add(name)
                try:
                    from app.world_manager import track_player_leave
                    track_player_leave(name)
                except Exception:
                    pass
                _notify_deduped("player_leave", player=name, players_online=len(players))
            continue
        m = MHDEATH_RE.search(line)
        if m:
            _notify_deduped("player_death", player=_player_name(m.group(1)), detail=m.group(2).strip())
            continue
        if DEATH_RE.search(line) and "Player" in line:
            _notify_deduped("player_death", player="Player", detail=line.strip()[-120:])
            continue
        if SERVER_STARTED_RE.search(line):
            players.clear()
            try:
                from app.world_manager import clear_active_play_sessions
                clear_active_play_sessions()
            except Exception:
                pass
            _notify_deduped("server_start")
            continue
        if SERVER_STOP_RE.search(line):
            players.clear()
            _notify_deduped("server_stop")

    reconciled = _build_player_set(_journal_lines("12 hours ago"))
    for name in reconciled - prev_known:
        if name in notified_joins:
            continue
        try:
            from app.world_manager import track_player_join
            track_player_join(name)
        except Exception:
            pass
        _track_player_registry(name)
        _notify_deduped("player_join", player=name, players_online=len(reconciled))
    for name in prev_known - reconciled:
        if name in notified_leaves:
            continue
        try:
            from app.world_manager import track_player_leave
            track_player_leave(name)
        except Exception:
            pass
        _notify_deduped("player_leave", player=name, players_online=len(reconciled))

    state["last_poll_at"] = poll_started_at
    state["connected_players"] = sorted(reconciled)
    _save_monitor_state(state)


def _disk_free_percent():
    try:
        stat = subprocess.run(
            ["df", "-P", "/"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        lines = stat.stdout.strip().splitlines()
        if len(lines) < 2:
            return 100
        parts = lines[1].split()
        return int(parts[3]) * 100 // (int(parts[2]) + int(parts[3]))
    except (OSError, ValueError, IndexError):
        return 100


def _memory_available_percent():
    try:
        meminfo = Path("/proc/meminfo").read_text(encoding="utf-8")
        total = avail = 0
        for line in meminfo.splitlines():
            if line.startswith("MemTotal:"):
                total = int(line.split()[1])
            elif line.startswith("MemAvailable:"):
                avail = int(line.split()[1])
        if total == 0:
            return 100
        return avail * 100 // total
    except (OSError, ValueError):
        return 100


def _cpu_percent():
    try:
        def snap():
            with open("/proc/stat") as f:
                parts = f.readline().split()
            nums = [int(x) for x in parts[1:8]]
            return nums[3], sum(nums)

        idle1, total1 = snap()
        time.sleep(0.2)
        idle2, total2 = snap()
        dt = total2 - total1
        di = idle2 - idle1
        if dt == 0:
            return 0
        return round((1 - di / dt) * 100)
    except OSError:
        return 0


def _poll_system_alerts():
    state = _load_monitor_state()
    alerts = state.get("alerts", {})
    now = time.time()
    cooldown = 3600

    disk_pct = _disk_free_percent()
    if disk_pct <= 10:
        last = alerts.get("ssd_warning", 0)
        if now - last > cooldown:
            notify("ssd_warning", detail=f"{disk_pct}%")
            alerts["ssd_warning"] = now

    mem_pct = _memory_available_percent()
    if mem_pct <= 15:
        last = alerts.get("memory_warning", 0)
        if now - last > cooldown:
            notify("memory_warning", detail=f"利用可能 {mem_pct}%")
            alerts["memory_warning"] = now

    cpu = _cpu_percent()
    if cpu >= 90:
        last = alerts.get("cpu_high", 0)
        if now - last > cooldown:
            notify("cpu_high", detail=f"{cpu}%")
            alerts["cpu_high"] = now

    state["alerts"] = alerts
    _save_monitor_state(state)


def _monitor_loop():
    tick = 0
    while True:
        try:
            _poll_journal_events()
            if tick % 6 == 0:
                _poll_system_alerts()
        except Exception:
            pass
        tick += 1
        time.sleep(POLL_INTERVAL_SEC)


def sync_online_play_sessions():
    try:
        from app.world_manager import get_active_world_folder, track_player_join
        if not get_active_world_folder():
            return
        for player in get_online_players():
            track_player_join(player)
    except Exception:
        pass


def start_monitor():
    global _monitor_started, _monitor_lock_fp
    if _monitor_started:
        return
    try:
        MONITOR_LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
        fp = open(MONITOR_LOCK_FILE, "w", encoding="utf-8")
        fcntl.flock(fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return
    _monitor_lock_fp = fp
    _monitor_started = True
    sync_online_play_sessions()
    thread = threading.Thread(target=_monitor_loop, daemon=True, name="discord-monitor")
    thread.start()
