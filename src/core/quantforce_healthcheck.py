#!/usr/bin/env python3
"""
QuantForce Labs 健康巡检
- 开机后自检
- 每天 09:00 ET 开盘前巡检
- 异常自愈 + Telegram 播报
"""
import time, requests, subprocess, shutil, os, sys
from datetime import datetime, timezone
import pytz

sys.path.insert(0, '/home/heng/QuantForce_Labs/src/core')
from telegram_notify import send

ET = pytz.timezone('America/New_York')

SERVICES = ['tech-scanner', 'quant-api', 'scanner-watchdog']
NODES = {
    'center':   '192.168.0.18',
    'executor': '192.168.0.11',
    'compute':  '192.168.0.143',
}
API = 'http://192.168.0.18:5800'

# ── 工具函数 ──────────────────────────────────────────

def check_service(name):
    r = subprocess.run(['systemctl', 'is-active', name], capture_output=True, text=True)
    return r.stdout.strip() == 'active'

def restart_service(name):
    subprocess.run(['sudo', 'systemctl', 'restart', name])
    time.sleep(5)
    return check_service(name)

def check_api():
    try:
        r = requests.get(f'{API}/health', timeout=5)
        return r.status_code == 200
    except:
        return False

def check_scanner_freshness():
    """检查三台上报是否新鲜（15分钟内）"""
    results = {}
    try:
        data = requests.get(f'{API}/scanner/status', timeout=5).json()
        now = time.time()
        for node in NODES:
            s = data.get(node, {})
            updated = s.get('updated_at')
            if updated:
                dt = datetime.fromisoformat(updated)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                age_min = (now - dt.timestamp()) / 60
                results[node] = age_min < 15
            else:
                results[node] = False
    except:
        for node in NODES:
            results[node] = False
    return results

def check_disk():
    usage = shutil.disk_usage('/')
    pct = usage.used / usage.total * 100
    return pct, usage.free // (1024**3)  # 返回使用率和剩余GB

def check_ssh(ip):
    r = subprocess.run(['ssh', '-o', 'ConnectTimeout=5', '-o', 'BatchMode=yes',
                        f'heng@{ip}', 'echo ok'], capture_output=True, text=True)
    return r.stdout.strip() == 'ok'

# ── 巡检主函数 ────────────────────────────────────────

def run_healthcheck(label="巡检"):
    lines = [f"🔍 <b>QuantForce Labs {label}</b>",
             f"时间: {datetime.now(ET).strftime('%Y-%m-%d %H:%M:%S ET')}",
             ""]
    ok = True

    # 1. 本机服务
    lines.append("📦 <b>服务状态</b>")
    for svc in SERVICES:
        alive = check_service(svc)
        if not alive:
            fixed = restart_service(svc)
            status = "✅ 已自愈" if fixed else "❌ 自愈失败"
            ok = False
        else:
            status = "✅"
        lines.append(f"  {svc}: {status}")

    # 2. API
    lines.append("")
    lines.append("🌐 <b>API</b>")
    api_ok = check_api()
    lines.append(f"  :5800/health: {'✅' if api_ok else '❌'}")
    if not api_ok:
        ok = False

    # 3. Scanner 数据新鲜度
    lines.append("")
    lines.append("📡 <b>Scanner 上报</b>")
    freshness = check_scanner_freshness()
    for node, fresh in freshness.items():
        lines.append(f"  {node}: {'✅ 新鲜' if fresh else '⚠️ 超时'}")
        if not fresh:
            ok = False

    # 4. 远端节点 SSH
    lines.append("")
    lines.append("🖥 <b>远端节点</b>")
    for node, ip in NODES.items():
        if ip == '192.168.0.18':
            continue
        ssh_ok = check_ssh(ip)
        lines.append(f"  {node} ({ip}): {'✅' if ssh_ok else '❌ SSH不通'}")
        if not ssh_ok:
            ok = False

    # 5. 磁盘
    lines.append("")
    lines.append("💾 <b>磁盘</b>")
    pct, free_gb = check_disk()
    disk_warn = pct > 85
    lines.append(f"  使用率: {pct:.1f}% | 剩余: {free_gb}GB {'⚠️' if disk_warn else '✅'}")
    if disk_warn:
        ok = False

    lines.append("")
    lines.append("✅ 全部正常" if ok else "⚠️ 存在异常，请关注")

    send('\n'.join(lines))
    return ok

# ── 主循环 ────────────────────────────────────────────

def main():
    # 启动时先跑一次
    time.sleep(30)  # 等其他服务起来
    run_healthcheck("开机自检")

    last_daily = None

    while True:
        now_et = datetime.now(ET)
        today = now_et.date()

        # 每天 09:00 ET 巡检
        if now_et.hour == 9 and now_et.minute == 0 and last_daily != today:
            run_healthcheck("开盘前巡检")
            last_daily = today

        time.sleep(60)

if __name__ == '__main__':
    main()
