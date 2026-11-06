"""
WARP Watchdog v2 — با retry و keepalive
"""
import subprocess
import time
import requests
from pathlib import Path
from datetime import datetime
import json

POOL_DIR = Path("/root/tg_master_bot/proxies/warp_pool")
STATE_FILE = Path("/root/tg_master_bot/proxies/healthy_ports.json")
CHECK_INTERVAL = 45
FAIL_THRESHOLD = 3  # بعد ۳ بار fail

def get_port(conf_path):
    try:
        for line in conf_path.read_text().splitlines():
            if "BindAddress" in line:
                return int(line.split(":")[-1].strip())
    except Exception:
        pass
    return None

def test_port(port, timeout=12):
    """تست SOCKS5 proxy"""
    try:
        r = requests.get(
            "https://api.ipify.org",
            proxies={
                "http": f"socks5h://127.0.0.1:{port}",
                "https": f"socks5h://127.0.0.1:{port}",
            },
            timeout=timeout
        )
        return r.text.strip() if r.status_code == 200 else None
    except Exception:
        return None

def restart_wireproxy(inst_dir, port):
    """restart یه wireproxy"""
    subprocess.run(["pkill", "-9", "-f", f"wireproxy.*{inst_dir}"],
                   capture_output=True)
    time.sleep(1)
    subprocess.Popen(
        ["wireproxy", "--config", "wireproxy.conf"],
        stdout=open(inst_dir / "wireproxy.log", "a"),
        stderr=subprocess.STDOUT,
        cwd=str(inst_dir)
    )
    # صبر بیشتر برای handshake
    time.sleep(8)

# پیدا کردن instanceها
instances = []
for d in sorted(POOL_DIR.glob("warp_*")):
    conf = d / "wireproxy.conf"
    if conf.exists():
        port = get_port(conf)
        if port:
            instances.append({"dir": d, "port": port, "fails": 0})

print(f"╔═══════════════════════════════════════╗")
print(f"║  🔄 WARP Watchdog v2                    ║")
print(f"╚═══════════════════════════════════════╝")
print(f"📦 Instances: {len(instances)}")
print(f"⏱️  Check: هر {CHECK_INTERVAL}s")
print(f"🔄 Restart: بعد {FAIL_THRESHOLD} بار fail")
print()

cycle = 0
while True:
    cycle += 1
    healthy_ips = {}
    dead_count = 0

    for inst in instances:
        port = inst["port"]
        ip = test_port(port)

        if ip:
            inst["fails"] = 0
            healthy_ips.setdefault(ip, []).append(port)
        else:
            inst["fails"] += 1
            dead_count += 1

            if inst["fails"] >= FAIL_THRESHOLD:
                print(f"  🔄 restart port {port} (fails={inst['fails']})")
                restart_wireproxy(inst["dir"], port)
                inst["fails"] = 0

                # تست مجدد
                ip2 = test_port(port)
                if ip2:
                    healthy_ips.setdefault(ip2, []).append(port)
                    print(f"     ✅ بعد از restart: {ip2}")

    # ذخیره state
    state = {
        "updated_at": datetime.now().isoformat(),
        "cycle": cycle,
        "total_instances": len(instances),
        "healthy_count": sum(len(p) for p in healthy_ips.values()),
        "dead_count": dead_count,
        "unique_ips": len(healthy_ips),
        "ip_to_ports": healthy_ips,
    }
    STATE_FILE.write_text(json.dumps(state, indent=2))

    print(f"[{datetime.now().strftime('%H:%M:%S')}] "
          f"🟢 سالم: {state['healthy_count']} | "
          f"🔴 خراب: {dead_count} | "
          f"🌐 IP یکتا: {state['unique_ips']}")

    time.sleep(CHECK_INTERVAL)
