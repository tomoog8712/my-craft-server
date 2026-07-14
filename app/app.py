#!/usr/bin/env python3
"""My Craft Server - Web UI Backend"""

import json
import os
import subprocess
import time
from pathlib import Path

from flask import Flask, jsonify, render_template, request

from app.port_check_manager import get_external_port_status, run_external_port_check

from app.update_manager import (
    delete_backup,
    get_backup_archive_path,
    get_installed_version,
    get_update_info,
    get_update_status,
    list_backups,
    restore_backup,
    start_update,
)

from app.settings_manager import (
    build_settings_response,
    get_visible_fields_by_key,
    read_properties as read_server_properties,
    settings_to_updates,
    write_properties,
)

from app.health_check_manager import (
    build_report_meta,
    build_report_text,
    get_check_definitions,
    run_all_checks,
    run_check,
)

from app.support_manager import (
    disable_support,
    enable_support,
    get_support_status,
    update_support_time,
)

from app.playit_manager import (
    create_playit_tunnel,
    disable_playit,
    disconnect_playit,
    enable_playit,
    get_bedrock_local_port,
    get_playit_status,
    start_playit_login,
    test_playit_connection,
)

from app.world_manager import (
    copy_world,
    create_world,
    create_world_backup,
    delete_world,
    delete_world_backup,
    export_world_path,
    get_current_world,
    get_dashboard_world,
    get_world,
    get_world_settings,
    import_world,
    list_world_backups,
    list_worlds,
    rename_world,
    restore_world_backup,
    switch_world,
    save_world_settings,
    update_world_meta,
)

from app.addon_manager import (
    analyze_addon_upload,
    delete_addon,
    get_addon_state,
    install_addon,
    restart_server_for_addons,
    rollback_addons,
    set_addon_enabled,
    sync_addons_to_all_worlds,
    upload_addons,
)

from app.reset_manager import (
    execute_reset,
    get_reset_catalog,
    preview_reset,
)

from app.discord_manager import (
    get_bedrock_uptime_label,
    get_discord_dashboard_status,
    get_discord_status,
    get_online_player_count,
    get_online_players,
    notify as discord_notify,
    save_event_settings,
    save_webhook_url,
    send_test_notification,
    start_monitor,
)

from app.player_manager import (
    get_banlist as get_player_banlist,
    get_home_summary as get_player_home_summary,
    list_players,
    perform_action as perform_player_action,
)


BASE_DIR = Path(__file__).resolve().parent.parent
APPLIANCE_DIR = Path("/etc/appliance")
MINECRAFT_DIR = Path("/opt/minecraft")




_DASHBOARD_CACHE = {"data": None, "at": 0.0}
DASHBOARD_CACHE_TTL = 8


app = Flask(
    __name__,
    template_folder=str(BASE_DIR / "templates"),
    static_folder=str(BASE_DIR / "static"),
)


def run_cmd(cmd, timeout=5):
    """Run a command without shell."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ""


def read_file(path):
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def get_cpu_percent():
    try:
        def snap():
            with open("/proc/stat") as f:
                parts = f.readline().split()
            nums = [int(x) for x in parts[1:8]]
            idle = nums[3]
            total = sum(nums)
            return idle, total

        idle1, total1 = snap()
        time.sleep(0.2)
        idle2, total2 = snap()
        dt = total2 - total1
        di = idle2 - idle1
        if dt == 0:
            return "0%"
        return f"{round((1 - di / dt) * 100)}%"
    except OSError:
        load = os.getloadavg()
        return f"load {load[0]:.2f}"


def get_memory():
    try:
        with open("/proc/meminfo") as f:
            info = {}
            for line in f:
                k, v = line.split(":", 1)
                info[k] = int(v.strip().split()[0])
        total = info.get("MemTotal", 0)
        avail = info.get("MemAvailable", 0)
        used = total - avail
        if total == 0:
            return "-"
        pct = round(used / total * 100)
        return f"{pct}% ({used // 1024}MB / {total // 1024}MB)"
    except OSError:
        return run_cmd(["free", "-h"]).split("\n")[1] if run_cmd(["free", "-h"]) else "-"


def get_disk():
    try:
        st = os.statvfs("/")
        total = st.f_blocks * st.f_frsize
        free = st.f_bavail * st.f_frsize
        used = total - free
        pct = round(used / total * 100) if total else 0
        return f"{pct}% ({used // (1024**3)}GB / {total // (1024**3)}GB)"
    except OSError:
        return "-"


def get_os_version():
    content = read_file("/etc/os-release")
    if 'PRETTY_NAME="' in content:
        return content.split('PRETTY_NAME="')[1].split('"')[0]
    return run_cmd(["lsb_release", "-d"]).split(":\t")[-1]


def get_server_status():
    status = run_cmd(["systemctl", "is-active", "bedrock"])
    return "running" if status == "active" else "stopped"


def get_product_id():
    serial = read_file(APPLIANCE_DIR / "serial")
    return serial if serial else "未設定"


def get_settings_value(key, default=""):
    content = read_file(APPLIANCE_DIR / "settings.conf")
    prefix = f"{key}="
    for line in content.splitlines():
        if line.startswith(prefix):
            return line.split("=", 1)[1].strip()
    return default


def get_external_port():
    return get_settings_value("EXTERNAL_PORT", "19132")


def get_lan_ip():
    now = time.time()
    cached = getattr(get_lan_ip, "_cache", None)
    if cached and now - cached["at"] < 30:
        return cached["ip"]
    ip_out = run_cmd(["hostname", "-I"])
    ip = ip_out.split()[0] if ip_out else ""
    get_lan_ip._cache = {"ip": ip, "at": now}
    return ip


def get_public_ip():
    now = time.time()
    cached = getattr(get_public_ip, "_cache", None)
    if cached and now - cached["at"] < 60:
        return cached["ip"]
    ip = run_cmd(["curl", "-4", "-fsSL", "--max-time", "3", "https://api.ipify.org"])
    get_public_ip._cache = {"ip": ip or "", "at": now}
    return ip


def build_external_summary(public_ip=None, playit=None, portcheck=None):
    if playit is None:
        playit = get_playit_status(poll_claim=False)
    if public_ip is None:
        public_ip = get_public_ip()
    if portcheck is None:
        portcheck = build_port_status(refresh_external=False, public_ip=public_ip)

    playit_ready = bool(playit.get("is_ready"))
    join_host = playit.get("join_host") or playit.get("host") or ""
    join_port = playit.get("port") or ""
    playit_target = f"{join_host}:{join_port}" if join_host and join_port else ""

    pf_open = portcheck.get("external_open") is True
    ext_port = portcheck.get("external_port") or get_external_port()
    pf_target = f"{public_ip}:{ext_port}" if public_ip else ""

    return {
        "playit_summary": {
            "state": "ready" if playit_ready else "not_ready",
            "state_label": "有効" if playit_ready else "無効",
            "connection_target": playit_target,
            "address": join_host,
            "port": str(join_port) if join_port else "",
        },
        "portforward_summary": {
            "state": "ready" if pf_open else "not_ready",
            "state_label": "開放済み" if pf_open else "未開放",
            "connection_target": pf_target,
            "external_open": portcheck.get("external_open"),
        },
        "lan_ip": get_lan_ip(),
        "public_ip": public_ip or "取得失敗",
        "external_port": ext_port,
        "playit": playit,
        "portcheck": portcheck,
    }


def build_port_status(refresh_external=False, public_ip=None):
    props = get_minecraft_props()
    internal_port = props.get("server-port", "19132")
    external_port = get_external_port()
    internal_ok = port_listening(int(internal_port))
    players = get_online_player_count()
    server_running = get_server_status() == "running"
    if public_ip is None:
        public_ip = get_public_ip()

    external = {}
    try:
        if refresh_external:
            external = run_external_port_check(public_ip, external_port, players_online=players)
        else:
            external = get_external_port_status(
                public_ip, external_port, refresh=False, players_online=players
            )
    except Exception as exc:
        external = {
            "external_open": None,
            "external_status": "確認失敗",
            "external_summary": str(exc)[:120],
            "checked_label": "",
        }

    external_open = external.get("external_open")
    external_status = external.get("external_status", "未確認")
    external_summary = external.get("external_summary", "")

    if not server_running:
        status = "サーバー停止中"
    elif not internal_ok:
        status = "内部ポート未待ち受け"
    elif external_open is True:
        status = external_status
        if players > 0:
            status = f"{external_status}（{players}人接続中）"
    elif external_open is False:
        status = external_status
    elif players > 0:
        status = f"内部稼働中（{players}人接続）"
    else:
        status = "内部待ち受け中"

    detail_parts = []
    if external_summary:
        detail_parts.append(external_summary)
    if external_open is False and internal_ok:
        detail_parts.append("ルーターでUDPポート転送を確認してください")
    elif external_open is True and external.get("source") == "active_players":
        detail_parts.append("グローバルIPへの直接応答は未確認ですが、接続実績があります")
    elif external_open is None and not refresh_external:
        detail_parts.append("「確認」ボタンでチェックできます")
    detail = " / ".join(detail_parts) if detail_parts else ""

    return {
        "external_port": external_port,
        "internal_port": internal_port,
        "internal_listening": internal_ok,
        "external_open": external_open,
        "external_status": external_status,
        "external_summary": external_summary,
        "external_checked_at": external.get("checked_label", ""),
        "external_checking": False,
        "status": status,
        "detail": detail,
        "public_ip": public_ip or "取得失敗",
        "lan_ip": get_lan_ip(),
        "connection_target": f"{public_ip}:{external_port}" if public_ip else "",
        "players_online": players,
        "server_running": server_running,
    }


def _now_label():
    return time.strftime("%Y-%m-%d %H:%M")


def get_appliance_config():
    try:
        raw = read_file(APPLIANCE_DIR / "config.json")
        return json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return {}


def get_minecraft_props():
    props = {}
    content = read_file(MINECRAFT_DIR / "server.properties")
    if not content:
        return props
    for line in content.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            props[k.strip()] = v.strip()
    return props


def get_mdns_hostname():
    return f"{run_cmd(['hostname'])}.local"


def port_listening(port):
    out = run_cmd(["ss", "-uln"])
    return f":{port}" in out or f"0.0.0.0:{port}" in out


def systemctl_bedrock(action):
    allowed = {"start", "stop", "restart"}
    if action not in allowed:
        return False, f"Invalid action: {action}"
    result = subprocess.run(
        ["sudo", "-n", "/usr/bin/systemctl", action, "bedrock"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode == 0:
        messages = {
            "start": "Server started.",
            "stop": "Server stopped.",
            "restart": "Server restarted.",
        }
        return True, messages[action]
    err = (result.stderr or result.stdout or "systemctl failed").strip()
    return False, err


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/settings")
def settings_page():
    return render_template("settings.html")


@app.route("/reset")
def reset_page():
    return render_template("reset.html")


@app.route("/api/reset/catalog")
def api_reset_catalog():
    try:
        return jsonify(get_reset_catalog())
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/reset/preview/<reset_id>")
def api_reset_preview(reset_id):
    try:
        return jsonify({"success": True, "preview": preview_reset(reset_id)})
    except ValueError as exc:
        return jsonify({"success": False, "message": str(exc)}), 400
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/reset/execute", methods=["POST"])
def api_reset_execute():
    try:
        data = request.get_json(force=True, silent=True) or {}
        ok, msg, reboot = execute_reset(
            data.get("reset_id", ""),
            data.get("admin_code", ""),
        )
        if not ok:
            return jsonify({"success": False, "message": msg}), 403
        return jsonify({"success": True, "message": msg, "reboot": reboot})
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/external")
def external_page():
    return render_template("external.html")


@app.route("/portforward")
def portforward_page():
    return render_template("portforward.html")


@app.route("/api/settings", methods=["GET"])
def api_settings_get():
    try:
        return jsonify(build_settings_response())
    except OSError as exc:
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/settings", methods=["POST"])
def api_settings_post():
    try:
        data = request.get_json(force=True, silent=True)
        if not data or not isinstance(data, dict):
            return jsonify({"success": False, "message": "Invalid JSON"}), 400

        _, allowed_keys = read_server_properties()
        fields_by_key = get_visible_fields_by_key()
        updates = settings_to_updates(data, set(allowed_keys.keys()), fields_by_key)
        if not updates:
            return jsonify({"success": False, "message": "No valid properties to save"}), 400
        write_properties(updates)
        return jsonify({"success": True, "message": "Settings saved"})
    except (OSError, ValueError, TypeError) as exc:
        return jsonify({"success": False, "message": str(exc)}), 500




@app.route("/update")
def update_page():
    return render_template("update.html")


@app.route("/backups")
def backups_page():
    return render_template("backups.html")


@app.route("/health")
def health_page():
    return render_template("health.html")


@app.route("/api/health/definitions")
def api_health_definitions():
    mode = request.args.get("mode", "normal")
    if mode not in ("normal", "qa"):
        mode = "normal"
    return jsonify({"mode": mode, "checks": get_check_definitions(mode)})


@app.route("/api/health/check/<check_id>")
def api_health_check(check_id):
    try:
        return jsonify(run_check(check_id))
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/health/run")
def api_health_run():
    mode = request.args.get("mode", "normal")
    if mode not in ("normal", "qa"):
        mode = "normal"
    try:
        report = run_all_checks(mode)
        report["report_text"] = build_report_text(report)
        return jsonify(report)
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/health/meta")
def api_health_meta():
    try:
        return jsonify(build_report_meta())
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/support")
def support_page():
    return render_template("support.html")


@app.route("/discord")
def discord_page():
    return render_template("discord.html")


@app.route("/api/discord")
def api_discord_get():
    try:
        return jsonify(get_discord_status())
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/discord/save", methods=["POST"])
def api_discord_save():
    try:
        data = request.get_json(force=True, silent=True) or {}
        ok, msg = save_webhook_url(data.get("webhook_url", ""))
        return jsonify({"success": ok, "message": msg})
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 400


@app.route("/api/discord/test", methods=["POST"])
def api_discord_test():
    try:
        ok, msg = send_test_notification()
        if ok:
            return jsonify({"success": True, "message": msg})
        return jsonify({"success": False, "message": msg}), 400
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/discord/settings", methods=["POST"])
def api_discord_settings():
    try:
        data = request.get_json(force=True, silent=True) or {}
        ok, msg = save_event_settings(data.get("events", {}))
        return jsonify({"success": ok, "message": msg})
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 400


@app.route("/api/support")
def api_support_get():
    try:
        return jsonify(get_support_status())
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/support/enable", methods=["POST"])
def api_support_enable():
    try:
        data = request.get_json(force=True, silent=True) or {}
        duration = data.get("duration", "1h")
        ok, msg = enable_support(duration)
        if ok:
            return jsonify({"success": True, "message": msg})
        return jsonify({"success": False, "message": msg}), 400
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/support/disable", methods=["POST"])
def api_support_disable():
    try:
        ok, msg = disable_support()
        if ok:
            return jsonify({"success": True, "message": msg})
        return jsonify({"success": False, "message": msg}), 400
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/support/time", methods=["POST"])
def api_support_time():
    try:
        data = request.get_json(force=True, silent=True) or {}
        duration = data.get("duration", "1h")
        ok, msg = update_support_time(duration)
        if ok:
            return jsonify({"success": True, "message": msg})
        return jsonify({"success": False, "message": msg}), 400
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/playit/status")
def api_playit_status():
    try:
        force = request.args.get("refresh", "").lower() in ("1", "true", "yes")
        return jsonify(get_playit_status(force_refresh=force, poll_claim=True))
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/playit/login", methods=["POST"])
def api_playit_login():
    try:
        ok, msg = start_playit_login()
        if ok:
            return jsonify({"success": True, "message": msg, "claim_url": msg if msg.startswith("http") else ""})
        return jsonify({"success": False, "message": msg}), 400
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/playit/test", methods=["POST"])
def api_playit_test():
    try:
        ok, msg = test_playit_connection()
        if ok:
            return jsonify({"success": True, "message": msg})
        return jsonify({"success": False, "message": msg}), 400
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/playit/enable", methods=["POST"])
def api_playit_enable():
    try:
        ok, msg = enable_playit()
        if ok:
            return jsonify({"success": True, "message": msg})
        return jsonify({"success": False, "message": msg}), 400
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/playit/disable", methods=["POST"])
def api_playit_disable():
    try:
        ok, msg = disable_playit()
        if ok:
            return jsonify({"success": True, "message": msg})
        return jsonify({"success": False, "message": msg}), 400
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/playit/create-tunnel", methods=["POST"])
def api_playit_create_tunnel():
    try:
        data = request.get_json(force=True, silent=True) or {}
        local_ip = data.get("local_ip") or "127.0.0.1"
        local_port = data.get("local_port")
        if local_port is not None:
            local_port = int(local_port)
        ok, msg = create_playit_tunnel(local_ip, local_port)
        if ok:
            return jsonify({"success": True, "message": msg, "playit": get_playit_status(force_refresh=True)})
        return jsonify({"success": False, "message": msg}), 400
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/playit/disconnect", methods=["POST"])
def api_playit_disconnect():
    try:
        ok, msg = disconnect_playit()
        if ok:
            return jsonify({
                "success": True,
                "message": msg,
                "playit": get_playit_status(poll_claim=True),
            })
        return jsonify({"success": False, "message": msg}), 400
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/update/info")
def api_update_info():
    try:
        return jsonify(get_update_info())
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/update/status")
def api_update_status():
    return jsonify(get_update_status())


@app.route("/api/update/start", methods=["POST"])
def api_update_start():
    ok, msg = start_update()
    if ok:
        return jsonify({"success": True, "message": msg})
    return jsonify({"success": False, "message": msg}), 400


@app.route("/api/backups")
def api_backups_list():
    try:
        return jsonify({"backups": list_backups()})
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/backups/<backup_id>/restore", methods=["POST"])
def api_backups_restore(backup_id):
    try:
        restore_backup(backup_id)
        return jsonify({"success": True, "message": "Backup restored"})
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/backups/<backup_id>/download")
def api_backups_download(backup_id):
    from flask import send_file
    from app.update_manager import _backup_archive_path
    try:
        path = _backup_archive_path(backup_id)
        if not path.exists():
            return jsonify({"success": False, "message": "Not found"}), 404
        return send_file(path, as_attachment=True, download_name=path.name)
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/backups/<backup_id>", methods=["DELETE"])
def api_backups_delete(backup_id):
    try:
        delete_backup(backup_id)
        return jsonify({"success": True, "message": "Deleted"})
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500

@app.route("/api/system")
def api_system():
    ip = run_cmd(["hostname", "-I"]).split()[0] if run_cmd(["hostname", "-I"]) else ""
    uptime = run_cmd(["uptime", "-p"])
    if not uptime:
        secs = float(read_file("/proc/uptime").split()[0]) if read_file("/proc/uptime") else 0
        h, rem = divmod(int(secs), 3600)
        m, _ = divmod(rem, 60)
        uptime = f"up {h} hours, {m} minutes"
    return jsonify({
        "hostname": get_mdns_hostname(),
        "ip": ip,
        "cpu": get_cpu_percent(),
        "memory": get_memory(),
        "disk": get_disk(),
        "uptime": uptime,
        "os": get_os_version(),
        "product_id": get_product_id(),
    })


@app.route("/api/server")
def api_server():
    status = get_server_status()
    return jsonify({
        "status": status,
        "status_label": "起動中" if status == "running" else "停止中",
        "can_control": True,
    })


@app.route("/api/server/start", methods=["POST"])
def api_server_start():
    ok, msg = systemctl_bedrock("start")
    if ok:
        discord_notify("server_start")
    return jsonify({"success": ok, "message": msg})


@app.route("/api/server/stop", methods=["POST"])
def api_server_stop():
    ok, msg = systemctl_bedrock("stop")
    if ok:
        discord_notify("server_stop")
    return jsonify({"success": ok, "message": msg})


@app.route("/api/server/restart", methods=["POST"])
def api_server_restart():
    ok, msg = systemctl_bedrock("restart")
    if ok:
        discord_notify("server_start")
    return jsonify({"success": ok, "message": msg})


@app.route("/api/lan")
def api_lan():
    props = get_minecraft_props()
    return jsonify({
        "hostname": get_mdns_hostname(),
        "ip": run_cmd(["hostname", "-I"]).split()[0] if run_cmd(["hostname", "-I"]) else "",
        "port": props.get("server-port", "19132"),
    })


@app.route("/api/external")
def api_external():
    public_ip = get_public_ip()
    playit = get_playit_status(poll_claim=False)
    return jsonify(_build_external_payload(public_ip, playit))


def _build_external_payload(public_ip=None, playit=None):
    if public_ip is None:
        public_ip = get_public_ip()
    if playit is None:
        playit = get_playit_status(poll_claim=False)
    portcheck = build_port_status(refresh_external=False, public_ip=public_ip)
    summary = build_external_summary(public_ip, playit, portcheck)
    return {
        "public_ip": summary["public_ip"],
        "last_ip": public_ip or "",
        "external_port": summary["external_port"],
        "lan_ip": summary["lan_ip"],
        "playit_summary": summary["playit_summary"],
        "portforward_summary": summary["portforward_summary"],
        "playit": playit,
        "portcheck": portcheck,
    }


@app.route("/api/portcheck")
def api_portcheck():
    refresh = request.args.get("refresh", "").lower() in ("1", "true", "yes")
    return jsonify(build_port_status(refresh_external=refresh))


@app.route("/api/minecraft")
def api_minecraft():
    props = get_minecraft_props()
    dash = get_dashboard_world()
    players = get_online_players()
    return jsonify({
        "players_online": dash.get("players_online", len(players)),
        "players_max": dash.get("players_max", int(props.get("max-players", "10"))),
        "players": players,
        "world_name": dash.get("display_name") or props.get("level-name", "Bedrock level"),
        "gamemode": dash.get("gamemode", props.get("gamemode", "-")),
        "difficulty": dash.get("difficulty", props.get("difficulty", "-")),
        "world_icon": dash.get("icon", "default"),
        "server_name": props.get("server-name", "my-craft-server"),
        "bedrock_version": get_installed_version(),
        "server_uptime": get_bedrock_uptime_label(),
    })


@app.route("/worlds")
def worlds_page():
    return render_template("worlds.html")


@app.route("/api/worlds")
def api_worlds_list():
    try:
        return jsonify(list_worlds())
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/worlds/current")
def api_worlds_current():
    try:
        return jsonify(get_current_world())
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/worlds/<world_id>")
def api_worlds_detail(world_id):
    try:
        return jsonify({"world": get_world(world_id)})
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/worlds/<world_id>/settings", methods=["GET"])
def api_worlds_settings_get(world_id):
    try:
        return jsonify({"success": True, "settings": get_world_settings(world_id)})
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/worlds/<world_id>/settings", methods=["POST"])
def api_worlds_settings_post(world_id):
    try:
        data = request.get_json(force=True, silent=True) or {}
        ok, result = save_world_settings(world_id, data)
        if ok:
            msg = "ワールド設定を保存しました"
            if isinstance(result, dict) and result.get("restarted"):
                msg = "ワールド設定を反映しました"
            elif isinstance(result, dict) and result.get("needs_restart"):
                msg += "（反映にはサーバー再起動が必要です）"
            return jsonify({"success": True, "message": msg, **(result if isinstance(result, dict) else {})})
        return jsonify({"success": False, "message": result}), 400
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/worlds/<world_id>/backups")
def api_worlds_backups_list(world_id):
    try:
        return jsonify({"backups": list_world_backups(world_id)})
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/worlds/create", methods=["POST"])
def api_worlds_create():
    try:
        data = request.get_json(force=True, silent=True) or {}
        ok, result = create_world(data)
        if ok:
            return jsonify({"success": True, "message": "作成しました", "world_id": result})
        return jsonify({"success": False, "message": result}), 400
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/worlds/switch", methods=["POST"])
def api_worlds_switch():
    try:
        data = request.get_json(force=True, silent=True) or {}
        world_id = data.get("id")
        ok, msg = switch_world(world_id)
        if ok:
            return jsonify({"success": True, "message": msg})
        return jsonify({"success": False, "message": msg}), 400
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/worlds/delete", methods=["POST"])
def api_worlds_delete():
    try:
        data = request.get_json(force=True, silent=True) or {}
        ok, msg = delete_world(data.get("id"), data.get("confirm_name", ""))
        if ok:
            return jsonify({"success": True, "message": msg})
        return jsonify({"success": False, "message": msg}), 400
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/worlds/copy", methods=["POST"])
def api_worlds_copy():
    try:
        data = request.get_json(force=True, silent=True) or {}
        ok, result = copy_world(data.get("id"))
        if ok:
            return jsonify({"success": True, "message": "コピーしました", "world_id": result})
        return jsonify({"success": False, "message": result}), 400
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/worlds/rename", methods=["POST"])
def api_worlds_rename():
    try:
        data = request.get_json(force=True, silent=True) or {}
        ok, msg = rename_world(data.get("id"), data.get("name"))
        if ok:
            return jsonify({"success": True, "message": msg})
        return jsonify({"success": False, "message": msg}), 400
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/worlds/meta", methods=["POST"])
def api_worlds_meta():
    try:
        data = request.get_json(force=True, silent=True) or {}
        ok, msg = update_world_meta(data.get("id"), data)
        if ok:
            return jsonify({"success": True, "message": msg})
        return jsonify({"success": False, "message": msg}), 400
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/worlds/backup", methods=["POST"])
def api_worlds_backup():
    try:
        data = request.get_json(force=True, silent=True) or {}
        backup_id, meta = create_world_backup(data.get("id"))
        return jsonify({"success": True, "message": "バックアップしました", "backup": meta})
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/worlds/restore", methods=["POST"])
def api_worlds_restore():
    try:
        data = request.get_json(force=True, silent=True) or {}
        ok, msg = restore_world_backup(data.get("id"), data.get("backup_id"))
        if ok:
            return jsonify({"success": True, "message": msg})
        return jsonify({"success": False, "message": msg}), 400
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/worlds/backup/delete", methods=["POST"])
def api_worlds_backup_delete():
    try:
        data = request.get_json(force=True, silent=True) or {}
        ok, msg = delete_world_backup(data.get("id"), data.get("backup_id"))
        return jsonify({"success": True, "message": msg})
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/worlds/import", methods=["POST"])
def api_worlds_import():
    from tempfile import NamedTemporaryFile
    try:
        upload = request.files.get("file")
        if not upload:
            return jsonify({"success": False, "message": "ファイルがありません"}), 400
        suffix = Path(upload.filename or "world.zip").suffix or ".zip"
        with NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            upload.save(tmp.name)
            ok, result = import_world(tmp.name, upload.filename)
        Path(tmp.name).unlink(missing_ok=True)
        if ok:
            return jsonify({"success": True, "message": "インポートしました", "world_id": result})
        return jsonify({"success": False, "message": result}), 400
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/worlds/export")
def api_worlds_export():
    from flask import send_file
    try:
        world_id = request.args.get("id")
        path = export_world_path(world_id)
        return send_file(path, as_attachment=True, download_name=path.name)
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500



@app.route("/players")
def players_page():
    return render_template("players.html")


@app.route("/api/players")
def api_players_list():
    try:
        sort = request.args.get("sort", "online")
        query = request.args.get("q", "")
        online = get_online_players()
        return jsonify(list_players(online_names=online, sort=sort, query=query))
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/players/bans")
def api_players_bans():
    try:
        return jsonify(get_player_banlist())
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/players/home")
def api_players_home():
    try:
        return jsonify(get_player_home_summary())
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/players/action", methods=["POST"])
def api_players_action():
    try:
        body = request.get_json(silent=True) or {}
        result = perform_player_action(
            body.get("action"),
            body.get("name"),
            permission=body.get("permission"),
        )
        return jsonify(result)
    except ValueError as exc:
        return jsonify({"success": False, "message": str(exc)}), 400
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/addons")
def addons_page():
    return render_template("addons.html")



@app.route("/api/addons")
def api_addons_get():
    try:
        return jsonify({"success": True, **get_addon_state()})
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/addons/upload", methods=["POST"])
def api_addons_upload():
    try:
        uploads = request.files.getlist("files") or request.files.getlist("file")
        uploads = [u for u in uploads if u and u.filename]
        force = request.form.get("force", "").lower() in ("1", "true", "yes")
        if not uploads:
            return jsonify({"success": False, "message": "ファイルを選択してください"}), 400
        saved = _save_addon_uploads(None, uploads)
        try:
            ok, result = upload_addons(saved, force=force)
            if not ok:
                return jsonify({"success": False, **result}), 409
            return jsonify({"success": True, **result})
        finally:
            for tmp, _name in saved:
                tmp.unlink(missing_ok=True)
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 400


@app.route("/api/addons/toggle", methods=["POST"])
def api_addons_toggle():
    try:
        data = request.get_json(force=True, silent=True) or {}
        pack_id = data.get("pack_id")
        enabled = bool(data.get("enabled"))
        restart = bool(data.get("restart"))
        if not pack_id:
            return jsonify({"success": False, "message": "pack_id が必要です"}), 400
        ok, result = set_addon_enabled(pack_id, enabled, restart=restart)
        return jsonify({"success": ok, **result})
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 400


@app.route("/api/addons/delete", methods=["POST"])
def api_addons_delete():
    try:
        data = request.get_json(force=True, silent=True) or {}
        pack_id = data.get("pack_id")
        restart = bool(data.get("restart"))
        if not pack_id:
            return jsonify({"success": False, "message": "pack_id が必要です"}), 400
        ok, result = delete_addon(pack_id, restart=restart)
        return jsonify({"success": ok, **result})
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 400


@app.route("/api/addons/rollback", methods=["POST"])
def api_addons_rollback():
    try:
        data = request.get_json(force=True, silent=True) or {}
        restart = bool(data.get("restart"))
        ok, result = rollback_addons(restart=restart)
        return jsonify({"success": ok, **result})
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 400


@app.route("/api/addons/restart", methods=["POST"])
def api_addons_restart():
    try:
        ok, result = restart_server_for_addons()
        if isinstance(result, dict):
            return jsonify({"success": ok, **result})
        return jsonify({"success": ok, "message": result})
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/worlds/<world_id>/addons")
def api_world_addons_get(world_id):
    try:
        return jsonify({"success": True, **get_addon_state()})
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/worlds/<world_id>/addons/analyze", methods=["POST"])
def api_world_addons_analyze(world_id):
    try:
        upload = request.files.get("file")
        if not upload or not upload.filename:
            return jsonify({"success": False, "message": "ファイルを選択してください"}), 400
        tmp = Path("/opt/appliance/work") / f"addon-upload-{_now_label().replace(' ', '-').replace(':', '')}-{upload.filename}"
        upload.save(tmp)
        try:
            result = analyze_addon_upload(tmp, upload.filename)
            return jsonify({"success": True, **result})
        finally:
            tmp.unlink(missing_ok=True)
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 400


def _save_addon_uploads(_unused, uploads):
    saved = []
    for upload in uploads:
        if not upload or not upload.filename:
            continue
        tmp = Path("/opt/appliance/work") / f"addon-upload-{os.getpid()}-{upload.filename}"
        upload.save(tmp)
        saved.append((tmp, upload.filename))
    return saved


@app.route("/api/worlds/<world_id>/addons/upload", methods=["POST"])
def api_world_addons_upload(world_id):
    try:
        uploads = request.files.getlist("files") or request.files.getlist("file")
        uploads = [u for u in uploads if u and u.filename]
        force = request.form.get("force", "").lower() in ("1", "true", "yes")
        if not uploads:
            return jsonify({"success": False, "message": "ファイルを選択してください"}), 400
        saved = _save_addon_uploads(world_id, uploads)
        try:
            ok, result = upload_addons(saved, force=force)
            if not ok:
                return jsonify({"success": False, **result}), 409
            return jsonify({"success": True, **result})
        finally:
            for tmp, _name in saved:
                tmp.unlink(missing_ok=True)
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 400


@app.route("/api/worlds/<world_id>/addons/install", methods=["POST"])
def api_world_addons_install(world_id):
    try:
        uploads = request.files.getlist("files") or request.files.getlist("file")
        if not uploads or not any(u and u.filename for u in uploads):
            single = request.files.get("file")
            uploads = [single] if single and single.filename else []
        uploads = [u for u in uploads if u and u.filename]
        force = request.form.get("force", "").lower() in ("1", "true", "yes")
        restart = request.form.get("restart", "").lower() in ("1", "true", "yes")
        if not uploads:
            return jsonify({"success": False, "message": "ファイルを選択してください"}), 400
        saved = _save_addon_uploads(world_id, uploads)
        try:
            ok, result = upload_addons(saved, force=force)
            if not ok:
                return jsonify({"success": False, **result}), 409
            if restart:
                ok2, result2 = restart_server_for_addons()
                if isinstance(result2, dict):
                    result.update(result2)
                else:
                    result["message"] = result2
                if not ok2:
                    return jsonify({"success": False, **result}), 400
            return jsonify({"success": True, **result})
        finally:
            for tmp, _name in saved:
                tmp.unlink(missing_ok=True)
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 400


@app.route("/api/worlds/<world_id>/addons/toggle", methods=["POST"])
def api_world_addons_toggle(world_id):
    try:
        data = request.get_json(force=True, silent=True) or {}
        pack_id = data.get("pack_id")
        enabled = bool(data.get("enabled"))
        restart = bool(data.get("restart"))
        if not pack_id:
            return jsonify({"success": False, "message": "pack_id が必要です"}), 400
        ok, result = set_addon_enabled(pack_id, enabled, restart=restart)
        return jsonify({"success": ok, **result})
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 400


@app.route("/api/worlds/<world_id>/addons/delete", methods=["POST"])
def api_world_addons_delete(world_id):
    try:
        data = request.get_json(force=True, silent=True) or {}
        pack_id = data.get("pack_id")
        restart = bool(data.get("restart"))
        if not pack_id:
            return jsonify({"success": False, "message": "pack_id が必要です"}), 400
        ok, result = delete_addon(pack_id, restart=restart)
        return jsonify({"success": ok, **result})
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 400


@app.route("/api/worlds/<world_id>/addons/rollback", methods=["POST"])
def api_world_addons_rollback(world_id):
    try:
        data = request.get_json(force=True, silent=True) or {}
        restart = bool(data.get("restart"))
        ok, result = rollback_addons(restart=restart)
        return jsonify({"success": ok, **result})
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 400


@app.route("/api/worlds/<world_id>/addons/restart", methods=["POST"])
def api_world_addons_restart(world_id):
    try:
        ok, msg = restart_server_for_addons()
        return jsonify({"success": ok, "message": msg})
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/log")
def api_log():
    raw = run_cmd(["journalctl", "-u", "bedrock", "-n", "10", "--no-pager", "-o", "cat"])
    lines = [ln for ln in raw.splitlines() if ln.strip()] if raw else []
    return jsonify({"logs": lines[-10:]})


def _build_dashboard_payload():
    public_ip = get_public_ip()
    playit = get_playit_status(poll_claim=False)
    external = _build_external_payload(public_ip, playit)
    return {
        "system": api_system().get_json(),
        "server": api_server().get_json(),
        "lan": api_lan().get_json(),
        "external": external,
        "minecraft": api_minecraft().get_json(),
        "players": get_player_home_summary(),
        "discord": get_discord_dashboard_status(),
        "log": api_log().get_json(),
    }


@app.route("/api/dashboard")
def api_dashboard():
    now = time.time()
    cached = _DASHBOARD_CACHE.get("data")
    if cached and now - _DASHBOARD_CACHE.get("at", 0) < DASHBOARD_CACHE_TTL:
        return jsonify(cached)
    payload = _build_dashboard_payload()
    _DASHBOARD_CACHE["data"] = payload
    _DASHBOARD_CACHE["at"] = now
    return jsonify(payload)


start_monitor()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
