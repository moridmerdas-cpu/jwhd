"""Build 118 WARP instances — 1 per account"""
import subprocess, time, re, random, json, sys, os, shutil
from pathlib import Path
from datetime import datetime

sys.path.insert(0, '/root/tg_master_bot')
from models import database as db

POOL = Path("/root/tg_master_bot/proxies/warp_pool")
MAP = Path("/root/tg_master_bot/proxies/account_proxy.json")
STATE = Path("/root/tg_master_bot/proxies/healthy_ports.json")
LOG = Path("/root/tg_master_bot/logs/build_118.log")

# 40 endpoint متفاوت
ENDPOINTS = []
for base in ["162.159.192", "162.159.193", "188.114.96", "188.114.97", "188.114.98", "188.114.99"]:
    for i in range(1, 7):
        ENDPOINTS.append(f"{base}.{i}:2408")
ENDPOINTS += [
    "engage.cloudflareclient.com:2408",
    "engage.cloudflareclient.com:500",
    "engage.cloudflareclient.com:1701",
    "162.159.204.1:894",
    "162.159.204.2:894",
    "162.159.195.1:2408",
]


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def test(port, t=6):
    try:
        r = subprocess.run(["curl", "-s", "--max-time", str(t),
                          "-x", f"socks5h://127.0.0.1:{port}",
                          "https://api.ipify.org"],
                         capture_output=True, text=True, timeout=t+3)
        ip = r.stdout.strip()
        if ip and ip.count(".") == 3:
            return ip
    except Exception:
        pass
    return None


def create_one(idx, port):
    d = POOL / f"w_{port}"
    d.mkdir(parents=True, exist_ok=True)
    try:
        r = subprocess.run(["wgcf", "register", "--accept-tos"],
                           cwd=d, capture_output=True, timeout=20)
        if r.returncode != 0:
            shutil.rmtree(d, ignore_errors=True)
            return None
        r = subprocess.run(["wgcf", "generate"], cwd=d,
                           capture_output=True, timeout=20)
        if r.returncode != 0:
            shutil.rmtree(d, ignore_errors=True)
            return None
        profile = d / "wgcf-profile.conf"
        if not profile.exists():
            shutil.rmtree(d, ignore_errors=True)
            return None

        ep = ENDPOINTS[idx % len(ENDPOINTS)]
        txt = profile.read_text()
        txt = re.sub(r'^Endpoint = .*$', f'Endpoint = {ep}', txt, flags=re.MULTILINE)
        if "PersistentKeepalive" not in txt:
            txt += "\nPersistentKeepalive = 25\n"
        profile.write_text(txt)

        (d / "wireproxy.conf").write_text(
            f"WGConfig = {profile}\n\n[Socks5]\nBindAddress = 127.0.0.1:{port}\n")

        lf = open(d / "wireproxy.log", "w")
        p = subprocess.Popen(["wireproxy", "--config", "wireproxy.conf"],
                             cwd=d, stdout=lf, stderr=subprocess.STDOUT)
        (d / "wireproxy.pid").write_text(str(p.pid))
        time.sleep(4)

        ip = test(port)
        if ip:
            return {"port": port, "ip": ip}
        return None
    except Exception:
        return None


def main():
    db.init_db()
    accounts = db.get_all_accounts()
    n = len(accounts)
    log(f"═" * 60)
    log(f"🚀 ساخت {n} WARP instance")
    log(f"═" * 60)

    alive = []

    for i, acc in enumerate(accounts):
        port = 40001 + i
        log(f"  [{i+1}/{n}] port {port}...")
        res = create_one(i, port)
        if res:
            alive.append(res)
            log(f"     ✅ {res['ip']}")
        else:
            log(f"     ❌ fail")
        if (i + 1) % 10 == 0:
            log(f"  📊 پیشرفت: {len(alive)}/{i+1}")
        time.sleep(2)  # صبر بین registerها

    log(f"\n✅ ساخته شد: {len(alive)}/{n}")

    # state
    ips = {}
    for a in alive:
        ips.setdefault(a["ip"], []).append(a["port"])

    STATE.write_text(json.dumps({
        "updated_at": datetime.now().isoformat(),
        "unique_ips": len(ips),
        "total_alive": len(alive),
        "ip_to_ports": ips,
        "port_to_ip": {str(a["port"]): a["ip"] for a in alive},
    }, indent=2))

    # ═══ 1:1 mapping ═══
    mapping = {}
    for i, acc in enumerate(accounts):
        if i < len(alive):
            a = alive[i]
            mapping[acc["phone"]] = {
                "source": "warp", "proxy_type": "socks5",
                "addr": "127.0.0.1", "port": a["port"], "ip": a["ip"],
            }
        else:
            # fallback round-robin
            a = alive[i % len(alive)] if alive else None
            if a:
                mapping[acc["phone"]] = {
                    "source": "warp", "proxy_type": "socks5",
                    "addr": "127.0.0.1", "port": a["port"], "ip": a["ip"],
                }

    MAP.write_text(json.dumps(mapping, indent=2))

    log(f"\n🌐 IP یگانه: {len(ips)}")
    log(f"🔌 alive: {len(alive)}")
    log(f"📊 mapping: {len(mapping)}")


if __name__ == "__main__":
    main()
