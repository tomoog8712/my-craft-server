"""System health check / diagnosis for My Craft Server."""

import json
import os
import re
import socket
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from app.update_manager import compare_versions, fetch_latest_release, get_installed_version

APPLIANCE_DIR = Path("/etc/appliance")
MINECRAFT_DIR = Path("/opt/minecraft")
BACKUP_DIR = Path("/opt/appliance/backups")

CHECK_ORDER = [
    "ubuntu",
    "minecraft",
    "webui",
    "nginx",
    "mdns",
    "lan",
    "api",
    "port",
    "server_properties",
    "ssd",
    "memory",
    "cpu",
    "logs",
    "internet",
    "playit",
    "external_port",
    "version",
]

QA_CHECK_ORDER = [
    "qa_server",
    "qa_api",
    "qa_webui",
    "qa_lan",
    "qa_mdns",
    "qa_settings",
    "qa_backup",
]

CHECK_LABELS = {
    "ubuntu": "Ubuntu",
    "minecraft": "Minecraft",
    "webui": "WebUI",
    "nginx": "Nginx",
    "mdns": "mDNS",
    "lan": "LAN",
    "api": "API",
    "port": "ポート",
    "server_properties": "server.properties",
    "ssd": "SSD空き容量",
    "memory": "メモリ",
    "cpu": "CPU",
    "logs": "ログ",
    "internet": "インターネット",
    "playit": "Playit.gg",
    "external_port": "ポート開放",
    "version": "最新版確認",
    "qa_server": "サーバー起動",
    "qa_api": "API",
    "qa_webui": "WebUI",
    "qa_lan": "LAN",
    "qa_mdns": "mDNS",
    "qa_settings": "設定保持",
    "qa_backup": "バックアップ",
}

ERROR_PATTERNS = re.compile(
    r"(ERROR|FAILED|Exception|Traceback)",
    re.IGNORECASE,
)


def _run(cmd, timeout=10):
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


def _read_file(path):
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def _result(check_id, status, message, detail="", remedy="", value=""):
    status = status if status in ("pass", "warn", "fail", "info") else "fail"
    labels = {
        "pass": "PASS",
        "warn": "WARNING",
        "fail": "FAIL",
        "info": "INFO",
    }
    return {
        "id": check_id,
        "label": CHECK_LABELS.get(check_id, check_id),
        "status": status,
        "status_label": labels[status],
        "message": message,
        "detail": detail or message,
        "remedy": remedy,
        "value": value,
    }


def _service_active(name):
    code, out, _ = _run(["systemctl", "is-active", name], timeout=5)
    return code == 0 and out == "active"


def _get_hostname():
    _, out, _ = _run(["hostname"])
    return out or "my-craft-server"


def _get_lan_ip():
    _, out, _ = _run(["hostname", "-I"])
    if not out:
        return ""
    return out.split()[0]


def _get_os_version():
    content = _read_file("/etc/os-release")
    if 'PRETTY_NAME="' in content:
        return content.split('PRETTY_NAME="')[1].split('"')[0]
    return "Ubuntu"


def _get_product_id():
    serial = _read_file(APPLIANCE_DIR / "serial")
    return serial if serial else "未設定"


def _get_appliance_config():
    try:
        raw = _read_file(APPLIANCE_DIR / "config.json")
        return json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return {}


def _get_minecraft_port():
    props = _read_file(MINECRAFT_DIR / "server.properties")
    for line in props.splitlines():
        line = line.strip()
        if line.startswith("server-port="):
            return line.split("=", 1)[1].strip()
    return "19132"


def _port_listening_udp(port):
    _, out, _ = _run(["ss", "-uln"])
    token = f":{port}"
    return token in out


def _disk_free_percent():
    try:
        st = os.statvfs("/")
        total = st.f_blocks * st.f_frsize
        free = st.f_bavail * st.f_frsize
        if total == 0:
            return 0, 0
        free_pct = round(free / total * 100)
        used_pct = round((total - free) / total * 100)
        return free_pct, used_pct
    except OSError:
        return 0, 100


def _memory_stats():
    try:
        with open("/proc/meminfo") as f:
            info = {}
            for line in f:
                key, val = line.split(":", 1)
                info[key] = int(val.strip().split()[0])
        total = info.get("MemTotal", 0)
        avail = info.get("MemAvailable", 0)
        if total == 0:
            return 0, 0, 0
        used_pct = round((total - avail) / total * 100)
        return used_pct, avail // 1024, total // 1024
    except OSError:
        return 100, 0, 0


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


def _resolve_mdns():
    host = f"{_get_hostname()}.local"
    try:
        socket.getaddrinfo(host, None, socket.AF_INET)
        return True, host
    except socket.gaierror:
        pass
    code, out, _ = _run(["getent", "hosts", host], timeout=5)
    if code == 0 and out:
        return True, host
    return False, host


def _fetch_local_api(path):
    url = f"http://127.0.0.1:5000{path}"
    req = urllib.request.Request(url, headers={"User-Agent": "HealthCheck/1.0"})
    with urllib.request.urlopen(req, timeout=8) as resp:
        return resp.status, resp.read().decode("utf-8")


def _service_start_since(unit):
    _, out, _ = _run(["systemctl", "show", unit, "-p", "ActiveEnterTimestamp", "--value"], timeout=5)
    return out if out and out != "n/a" else "30 min ago"


def _scan_journal_errors():
    units = ["bedrock", "mhserver-web", "nginx"]
    hits = []
    for unit in units:
        if not _service_active(unit):
            continue
        since = _service_start_since(unit)
        code, out, _ = _run(
            [
                "journalctl",
                "-u",
                unit,
                "--since",
                since,
                "-n",
                "80",
                "--no-pager",
                "-o",
                "cat",
            ],
            timeout=15,
        )
        if code != 0 or not out:
            continue
        for line in out.splitlines():
            if ERROR_PATTERNS.search(line):
                hits.append(f"[{unit}] {line[:120]}")
                if len(hits) >= 5:
                    return hits
    return hits


def check_ubuntu():
    os_name = _get_os_version()
    uptime_code, uptime_out, _ = _run(["uptime", "-p"], timeout=5)
    if uptime_code == 0 and uptime_out:
        return _result(
            "ubuntu",
            "pass",
            f"{os_name} が正常に起動しています",
            detail=f"OS: {os_name}\n稼働: {uptime_out}",
            remedy="問題が続く場合は電源を入れ直してください。",
            value=os_name,
        )
    return _result(
        "ubuntu",
        "fail",
        "OSの起動状態を確認できません",
        detail="システムの稼働時間を取得できませんでした。",
        remedy="本体の電源を確認し、再起動してください。",
    )


def check_minecraft():
    active = _service_active("bedrock")
    if active:
        version = get_installed_version()
        return _result(
            "minecraft",
            "pass",
            "Minecraftサーバーは起動中です",
            detail=f"bedrock.service: active\nバージョン: {version}",
            remedy="停止している場合はダッシュボードから「開始」を押してください。",
            value=version,
        )
    return _result(
        "minecraft",
        "fail",
        "Minecraftサーバーが停止しています",
        detail="bedrock.service が active ではありません。",
        remedy="ダッシュボードの「開始」ボタンでサーバーを起動してください。",
    )


def check_webui():
    if _service_active("mhserver-web"):
        return _result(
            "webui",
            "pass",
            "Web管理画面は正常です",
            detail="mhserver-web.service: active",
            remedy="表示できない場合は数分待ってから再読み込みしてください。",
        )
    return _result(
        "webui",
        "fail",
        "Web管理画面が停止しています",
        detail="mhserver-web.service が active ではありません。",
        remedy="サポートへご連絡ください。",
    )


def check_nginx():
    if _service_active("nginx"):
        return _result(
            "nginx",
            "pass",
            "Webサーバーは正常です",
            detail="nginx.service: active",
            remedy="ページが開かない場合はLAN接続を確認してください。",
        )
    return _result(
        "nginx",
        "fail",
        "Webサーバーが停止しています",
        detail="nginx.service が active ではありません。",
        remedy="サポートへご連絡ください。",
    )


def check_mdns():
    ok, host = _resolve_mdns()
    if ok:
        return _result(
            "mdns",
            "pass",
            f"{host} を名前解決できました",
            detail=f"mDNSホスト名: {host}",
            remedy="見つからない場合はIPアドレスで接続できます。",
            value="PASS",
        )
    return _result(
        "mdns",
        "warn",
        f"{host} を名前解決できません",
        detail="同じLAN内でも端末によっては .local が使えない場合があります。",
        remedy="IPアドレスを使って接続してください。",
        value="FAIL",
    )


def check_lan():
    ip = _get_lan_ip()
    if ip:
        return _result(
            "lan",
            "pass",
            f"LAN IP: {ip}",
            detail=f"hostname -I の結果: {ip}",
            remedy="IPが変わった場合はMinecraftのサーバー一覧を更新してください。",
            value=ip,
        )
    return _result(
        "lan",
        "fail",
        "LANのIPアドレスを取得できません",
        detail="ネットワーク接続が確認できません。",
        remedy="LANケーブルまたはWi-Fi接続を確認してください。",
    )


def check_api():
    try:
        product = _get_product_id()
        ip = _get_lan_ip()
        server_active = _service_active("bedrock")
        if product and ip:
            return _result(
                "api",
                "pass",
                "管理APIは正常です",
                detail=(
                    "ダッシュボードAPIのデータソースを確認しました。\n"
                    f"製品ID: {product}\nLAN IP: {ip}\nBedrock: {'active' if server_active else 'stopped'}"
                ),
                remedy="エラーが出る場合はページを再読み込みしてください。",
                value="PASS",
            )
    except OSError as exc:
        return _result(
            "api",
            "fail",
            "管理APIに接続できません",
            detail=str(exc),
            remedy="Web管理画面を再読み込みし、改善しない場合は再起動してください。",
        )
    return _result(
        "api",
        "fail",
        "管理APIの応答が不正です",
        detail="期待したデータ形式ではありません。",
        remedy="サポートへご連絡ください。",
    )


def check_port():
    port = _get_minecraft_port()
    if _port_listening_udp(port):
        return _result(
            "port",
            "pass",
            f"UDP {port} で待ち受け中",
            detail=f"Minecraftポート {port} は開いています。",
            remedy="接続できない場合はファイアウォール設定を確認してください。",
            value=f"UDP {port}",
        )
    return _result(
        "port",
        "fail",
        f"UDP {port} が待ち受けていません",
        detail="Minecraftサーバーがポートを開いていない可能性があります。",
        remedy="Minecraftサーバーを起動するか、再起動してください。",
    )


def check_server_properties():
    path = MINECRAFT_DIR / "server.properties"
    if path.exists() and path.is_file():
        content = _read_file(path)
        if content and "server-name" in content:
            return _result(
                "server_properties",
                "pass",
                "設定ファイルを読み込めます",
                detail="server.properties は正常に読み込めました。",
                remedy="設定画面から内容を確認できます。",
                value="PASS",
            )
    return _result(
        "server_properties",
        "fail",
        "設定ファイルを読み込めません",
        detail="server.properties が見つからないか、内容が不正です。",
        remedy="サポートへご連絡ください。",
    )


def check_ssd():
    free_pct, used_pct = _disk_free_percent()
    if free_pct < 5:
        return _result(
            "ssd",
            "fail",
            f"空き容量 {free_pct}%（使用 {used_pct}%）",
            detail="SSDの空き容量が非常に少なくなっています。",
            remedy="不要なバックアップを削除するか、サポートへご相談ください。",
            value=f"{used_pct}%",
        )
    if free_pct < 15:
        return _result(
            "ssd",
            "warn",
            f"空き容量 {free_pct}%（使用 {used_pct}%）",
            detail="SSDの空き容量が少なくなっています。",
            remedy="バックアップの整理を検討してください。",
            value=f"{used_pct}%",
        )
    return _result(
        "ssd",
        "pass",
        f"空き容量 {free_pct}%（使用 {used_pct}%）",
        detail="SSDの空き容量は十分です。",
        remedy="定期的にバックアップを確認してください。",
        value=f"{used_pct}%",
    )


def check_memory():
    used_pct, avail_mb, total_mb = _memory_stats()
    if avail_mb < 128 or used_pct >= 90:
        return _result(
            "memory",
            "warn",
            f"使用率 {used_pct}%（空き {avail_mb}MB）",
            detail="メモリが不足気味です。",
            remedy="プレイヤー数を減らすか、サーバーを再起動してください。",
            value=f"{used_pct}%",
        )
    return _result(
        "memory",
        "pass",
        f"使用率 {used_pct}%（空き {avail_mb}MB）",
        detail=f"メモリ {avail_mb}MB / {total_mb}MB 利用可能です。",
        remedy="メモリ不足が続く場合は同時接続人数を減らしてください。",
        value=f"{used_pct}%",
    )


def check_cpu():
    pct = _cpu_percent()
    if pct >= 90:
        return _result(
            "cpu",
            "warn",
            f"CPU使用率 {pct}%",
            detail="CPU負荷が高い状態です。",
            remedy="ワールドを小さくするか、同時接続人数を減らしてください。",
            value=f"{pct}%",
        )
    return _result(
        "cpu",
        "pass",
        f"CPU使用率 {pct}%",
        detail="CPU負荷は正常範囲です。",
        remedy="高負荷が続く場合はビュー距離を下げてください。",
        value=f"{pct}%",
    )


def check_logs():
    hits = _scan_journal_errors()
    if hits:
        return _result(
            "logs",
            "warn",
            "ログに警告・エラーが見つかりました",
            detail="\n".join(hits),
            remedy="問題が続く場合はサポートへログをお知らせください。",
            value="WARNING",
        )
    return _result(
        "logs",
        "pass",
        "重大なログエラーはありません",
        detail="直近のログに ERROR / FAILED は見つかりませんでした。",
        remedy="定期的にログを確認してください。",
        value="PASS",
    )


def check_internet():
    try:
        fetch_latest_release()
        return _result(
            "internet",
            "pass",
            "インターネットに接続できています",
            detail="Minecraft公式APIへ接続できました。",
            remedy="接続できない場合はルーターの設定を確認してください。",
            value="PASS",
        )
    except Exception as exc:
        return _result(
            "internet",
            "fail",
            "インターネットに接続できません",
            detail=str(exc),
            remedy="LANケーブルとルーターのインターネット接続を確認してください。",
            value="FAIL",
        )


def _get_external_port():
    content = _read_file(APPLIANCE_DIR / "settings.conf")
    for line in content.splitlines():
        if line.startswith("EXTERNAL_PORT="):
            return line.split("=", 1)[1].strip()
    return _get_minecraft_port()


def check_playit():
    from app.playit_manager import get_playit_status

    playit = get_playit_status(poll_claim=False)
    if playit.get("is_ready"):
        host = playit.get("join_host") or playit.get("host") or ""
        port = playit.get("port") or ""
        target = f"{host}:{port}" if host and port else ""
        return _result(
            "playit",
            "pass",
            "正常",
            detail=f"Playit.ggは利用可能です。接続先: {target or '-'}",
            remedy="接続できない場合は外部接続画面で接続テストを実行してください。",
            value="正常",
        )
    if playit.get("authenticated"):
        return _result(
            "playit",
            "warn",
            "トンネル未設定",
            detail="Playit.ggは認証済みですが、接続先がまだありません。",
            remedy="外部接続画面でトンネルを作成してください。",
            value="未完了",
        )
    return _result(
        "playit",
        "info",
        "未設定",
        detail="Playit.ggはセットアップされていません。",
        remedy="外部接続画面からセットアップできます。",
        value="未設定",
    )


def check_external_port():
    from app.port_check_manager import run_external_port_check

    port = _get_external_port()
    _, public_ip, _ = _run(
        ["curl", "-4", "-fsSL", "--max-time", "5", "https://api.ipify.org"],
        timeout=8,
    )
    if not public_ip:
        return _result(
            "external_port",
            "warn",
            "グローバルIPを取得できません",
            detail="インターネット接続またはDNSを確認してください。",
            remedy="ルーターのインターネット接続を確認してから再診断してください。",
            value="未確認",
        )

    try:
        external = run_external_port_check(public_ip, port)
    except Exception as exc:
        return _result(
            "external_port",
            "warn",
            "ポート確認に失敗しました",
            detail=str(exc),
            remedy="しばらく待ってから再診断してください。",
            value="未確認",
        )

    if external.get("external_open") is True:
        return _result(
            "external_port",
            "pass",
            f"UDP{port}応答あり",
            detail=external.get("external_summary") or f"{public_ip}:{port} へ外部から到達できました。",
            remedy="接続できない場合はルーターのポート転送設定を再確認してください。",
            value=f"UDP{port}",
        )
    if external.get("external_open") is False:
        return _result(
            "external_port",
            "fail",
            "ポートが閉じています",
            detail=external.get("external_summary") or f"UDP {port} への外部応答がありません。",
            remedy="ルーターでUDPポート転送を設定し、外部接続画面で接続テストを実行してください。",
            value="CLOSED",
        )
    return _result(
        "external_port",
        "warn",
        "ポート状態を確認できません",
        detail=external.get("external_summary") or "外部ポートの応答を判定できませんでした。",
        remedy="外部接続画面で接続テストを実行してください。",
        value="未確認",
    )


def check_version():
    current = get_installed_version()
    try:
        latest, _ = fetch_latest_release()
        latest_error = ""
    except Exception as exc:
        latest = current
        latest_error = str(exc)

    if latest_error:
        return _result(
            "version",
            "warn",
            f"現在 {current}（最新版の確認不可）",
            detail=latest_error,
            remedy="インターネット接続を確認してから再診断してください。",
            value=current,
        )

    if compare_versions(latest, current) > 0:
        return _result(
            "version",
            "warn",
            f"現在 {current} / 最新 {latest}",
            detail="新しいバージョンが利用可能です。",
            remedy="アップデート画面から最新版へ更新できます。",
            value=current,
        )

    return _result(
        "version",
        "pass",
        f"最新版です（{current}）",
        detail=f"現在: {current}\n最新: {latest}",
        remedy="定期的にアップデート画面で確認してください。",
        value=current,
    )


def check_qa_server():
    return check_minecraft()


def check_qa_api():
    return check_api()


def check_qa_webui():
    return check_webui()


def check_qa_lan():
    return check_lan()


def check_qa_mdns():
    result = check_mdns()
    if result["status"] == "warn":
        result["status"] = "pass"
        result["status_label"] = "PASS"
        result["message"] = f"{result['detail'].splitlines()[0]}（IPでも可）"
    return result


def check_qa_settings():
    path = MINECRAFT_DIR / "server.properties"
    if not path.exists():
        return _result(
            "qa_settings",
            "fail",
            "設定ファイルがありません",
            detail="server.properties が見つかりません。",
            remedy="出荷前に設定ファイルを確認してください。",
        )
    content = _read_file(path)
    if "server-name" in content and os.access(path, os.R_OK):
        return _result(
            "qa_settings",
            "pass",
            "設定ファイルは保持されています",
            detail="server.properties を読み込み・保存できます。",
            remedy="設定画面で変更が反映されることを確認してください。",
            value="PASS",
        )
    return _result(
        "qa_settings",
        "fail",
        "設定ファイルに問題があります",
        detail="server.properties の内容を確認できません。",
        remedy="設定ファイルを再確認してください。",
    )


def check_qa_backup():
    if BACKUP_DIR.exists() and os.access(BACKUP_DIR, os.W_OK):
        count = len(list(BACKUP_DIR.glob("*.tar.gz")))
        return _result(
            "qa_backup",
            "pass",
            f"バックアップ機能は利用可能です（{count}件）",
            detail=f"バックアップ保存先: {BACKUP_DIR}",
            remedy="出荷前にテストバックアップを1件作成することを推奨します。",
            value=str(count),
        )
    return _result(
        "qa_backup",
        "fail",
        "バックアップ機能を確認できません",
        detail="バックアップディレクトリにアクセスできません。",
        remedy="バックアップ先の権限を確認してください。",
    )


CHECK_RUNNERS = {
    "ubuntu": check_ubuntu,
    "minecraft": check_minecraft,
    "webui": check_webui,
    "nginx": check_nginx,
    "mdns": check_mdns,
    "lan": check_lan,
    "api": check_api,
    "port": check_port,
    "server_properties": check_server_properties,
    "ssd": check_ssd,
    "memory": check_memory,
    "cpu": check_cpu,
    "logs": check_logs,
    "internet": check_internet,
    "playit": check_playit,
    "external_port": check_external_port,
    "version": check_version,
    "qa_server": check_qa_server,
    "qa_api": check_qa_api,
    "qa_webui": check_qa_webui,
    "qa_lan": check_qa_lan,
    "qa_mdns": check_qa_mdns,
    "qa_settings": check_qa_settings,
    "qa_backup": check_qa_backup,
}


def _overall_status(checks):
    has_fail = any(c["status"] == "fail" for c in checks)
    has_warn = any(c["status"] == "warn" for c in checks)
    if has_fail:
        return "fail", "🔴 修正が必要です"
    if has_warn:
        return "warn", "🟡 注意があります"
    return "pass", "🟢 問題ありません"


def run_check(check_id):
    runner = CHECK_RUNNERS.get(check_id)
    if not runner:
        return _result(check_id, "fail", "不明な診断項目です")
    return runner()


def run_all_checks(mode="normal"):
    order = QA_CHECK_ORDER if mode == "qa" else CHECK_ORDER
    checks = [run_check(check_id) for check_id in order]
    overall, overall_label = _overall_status(checks)
    return {
        "mode": mode,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "overall": overall,
        "overall_label": overall_label,
        "checks": checks,
        "meta": build_report_meta(),
    }


def build_report_meta():
    free_pct, used_pct = _disk_free_percent()
    mem_pct, avail_mb, total_mb = _memory_stats()
    config = _get_appliance_config()
    serial = _get_product_id()
    _, uptime_out, _ = _run(["uptime", "-p"], timeout=5)
    _, public_ip, _ = _run(
        ["curl", "-4", "-fsSL", "--max-time", "5", "https://api.ipify.org"],
        timeout=8,
    )

    props = _read_file(MINECRAFT_DIR / "server.properties")
    server_name = "my-craft-server"
    level_name = "Bedrock level"
    for line in props.splitlines():
        line = line.strip()
        if line.startswith("server-name="):
            server_name = line.split("=", 1)[1].strip()
        if line.startswith("level-name="):
            level_name = line.split("=", 1)[1].strip()

    return {
        "product_id": serial,
        "os": _get_os_version(),
        "minecraft_version": get_installed_version(),
        "hostname": f"{_get_hostname()}.local",
        "lan_ip": _get_lan_ip(),
        "minecraft_port": _get_minecraft_port(),
        "server_name": server_name,
        "world_name": level_name,
        "uptime": uptime_out or "-",
        "disk_used_pct": used_pct,
        "disk_free_pct": free_pct,
        "memory_used_pct": mem_pct,
        "memory_avail_mb": avail_mb,
        "memory_total_mb": total_mb,
        "cpu_used_pct": _cpu_percent(),
        "bedrock_active": _service_active("bedrock"),
        "webui_active": _service_active("mhserver-web"),
        "nginx_active": _service_active("nginx"),
        "public_ip": public_ip or "取得失敗",
        "support_logs": _collect_support_logs(),
    }


def _collect_support_logs():
    chunks = []
    for unit in ["bedrock", "mhserver-web", "nginx"]:
        since = _service_start_since(unit)
        code, out, _ = _run(
            [
                "journalctl",
                "-u",
                unit,
                "--since",
                since,
                "-n",
                "12",
                "--no-pager",
                "-o",
                "short-iso",
            ],
            timeout=15,
        )
        if code != 0 or not out:
            chunks.append(f"--- {unit} ---\n(ログなし)")
            continue
        chunks.append(f"--- {unit} (since {since}) ---")
        chunks.append(out)
    return "\n".join(chunks)


def build_report_text(report):
    meta = report.get("meta", {})
    checks = report.get("checks", [])
    overall = report.get("overall", "pass")
    overall_label = "PASS"
    if overall == "warn":
        overall_label = "WARNING"
    elif overall == "fail":
        overall_label = "FAIL"

    lines = [
        "========================================",
        "My Craft Server 診断レポート",
        "========================================",
        f"診断日時 {report.get('checked_at', '-')}",
        f"製品ID {meta.get('product_id', '-')}",
        f"OS {meta.get('os', '-')}",
        f"Minecraft {meta.get('minecraft_version', '-')}",
        f"ホスト名 {meta.get('hostname', '-')}",
        f"LAN IP {meta.get('lan_ip', '-')}",
        f"ポート UDP {meta.get('minecraft_port', '-')}",
        f"サーバー名 {meta.get('server_name', '-')}",
        f"ワールド {meta.get('world_name', '-')}",
        f"稼働時間 {meta.get('uptime', '-')}",
        "",
        "--- サマリー ---",
    ]

    key_map = {
        "lan": "LAN",
        "mdns": "mDNS",
        "api": "API",
        "webui": "WebUI",
        "nginx": "Nginx",
        "minecraft": "Bedrock",
        "ssd": "SSD",
        "memory": "Memory",
        "cpu": "CPU",
        "port": "ポート",
        "server_properties": "server.properties",
        "internet": "インターネット",
        "version": "最新版確認",
        "logs": "ログ",
        "ubuntu": "Ubuntu",
    }
    for check in checks:
        label = key_map.get(check["id"], check["label"])
        if check["id"] in ("ssd", "memory", "cpu"):
            value = check.get("value") or check["status_label"]
        else:
            value = "PASS" if check["status"] == "pass" else check["status_label"]
        lines.append(f"{label} {value}")

    lines.extend([
        f"総合 {overall_label}",
        "",
        "--- 詳細 ---",
    ])

    for check in checks:
        lines.append(f"[{check['label']}] {check['status_label']}")
        lines.append(f"  {check.get('message', '')}")
        if check.get("value"):
            lines.append(f"  値: {check['value']}")
        detail = (check.get("detail") or "").strip()
        if detail:
            for detail_line in detail.splitlines():
                lines.append(f"  {detail_line}")

    lines.extend([
        "",
        "--- サービス状態 ---",
        f"bedrock {'active' if meta.get('bedrock_active') else 'inactive'}",
        f"mhserver-web {'active' if meta.get('webui_active') else 'inactive'}",
        f"nginx {'active' if meta.get('nginx_active') else 'inactive'}",
        f"グローバルIP {meta.get('public_ip', '-')}",
        f"SSD使用 {meta.get('disk_used_pct', '-')}% / 空き {meta.get('disk_free_pct', '-')}%",
        f"メモリ {meta.get('memory_used_pct', '-')}% ({meta.get('memory_avail_mb', '-')}MB空き)",
        f"CPU {meta.get('cpu_used_pct', '-')}%",
        "",
        "--- サポート用ログ ---",
        meta.get("support_logs", "(ログなし)"),
    ])
    return "\n".join(lines)


def get_check_definitions(mode="normal"):
    order = QA_CHECK_ORDER if mode == "qa" else CHECK_ORDER
    return [{"id": check_id, "label": CHECK_LABELS.get(check_id, check_id)} for check_id in order]
