"""
ساخت 78 instance WARP — یکی برای هر اکانت
- هر instance endpoint متفاوت
- صبر بین create
- ذخیره در account_proxy (1:1)
"""
import subprocess, time, re, random, json, sys, os, shutil
from pathlib import Path
from datetime import datetime

sys.path.insert(0, '/root/tg_master_bot')
from models import database as db

POOL = Path("/root/tg_master_bot/proxies/warp_pool")
MAP = Path("/root/tg_master_bot/proxies/account_proxy.json")
STATE = Path("/root/tg_master_bot/proxies/healthy_ports.json")
LOG = Path("/root/tg_master_bot/logs/build_1to1.log")

# ═══ ۳۰ endpoint ═══
ENDPOINTS = []
for base in ["162.159.192", "162.159.193", "188.114.96", "188.114.97", "188.114.98", "188.114.99"]:
    for i in range(1, 6):
        ENDPOINTS.append(f"{base}.{i}:2408")
ENDPOINTS += [
    "engage.cloudflareclient.com:2408",
    "engage.cloudflareclient.com:500",
    "engage.cloudflareclient.com:1701",
    "162.159.204.1:894",
    "162.159.204.2:894",
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
    """ساخت یه instance"""
    d = POOL / f"w_{port}"
    d.mkdir(parents=True, exist_ok=True)

    try:
        # register
        r = subprocess.run(["wgcf", "register", "--accept-tos"],
                           cwd=d, capture_output=True, timeout=20)
        if r.returncode != 0:
            shutil.rmtree(d, ignore_errors=True)
            return None

        # generate
        r = subprocess.run(["wgcf", "generate"], cwd=d,
                           capture_output=True, timeout=20)
        if r.returncode != 0:
            shutil.rmtree(d, ignore_errors=True)
            return None

        profile = d / "wgcf-profile.conf"
        if not profile.exists():
            shutil.rmtree(d, ignore_errors=True)
            return None

        # endpoint متفاوت
        ep = ENDPOINTS[idx % len(ENDPOINTS)]
        txt = profile.read_text()
        txt = re.sub(r'^Endpoint = .*$', f'Endpoint = {ep}', txt, flags=re.MULTILINE)
        if "PersistentKeepalive" not in txt:
            txt += "\nPersistentKeepalive = 25\n"
        profile.write_text(txt)

        (d / "wireproxy.conf").write_text(
            f"WGConfig = {profile}\n\n[Socks5]\nBindAddress = 127.0.0.1:{port}\n")

        # run
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
    log(f"🚀 ساخت {n} instance (1 per account)")
    log(f"═" * 60)

    alive = []  # [{port, ip}]

    for i, acc in enumerate(accounts):
        port = 40001 + i
        log(f"  [{i+1}/{n}] ساخت port {port}...")

        res = create_one(i, port)
        if res:
            alive.append(res)
            log(f"     ✅ {res['ip']}")
        else:
            log(f"     ❌ fail")

        # ذخیره پیشرفت هر 5 تا
        if (i + 1) % 5 == 0:
            log(f"  📊 پیشرفت: {len(alive)}/{i+1}")

        # صبر بین create
        time.sleep(3)

    log(f"\n✅ ساخته شد: {len(alive)}/{n}")

    # ═══ ذخیره state ═══
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

    # ═══ mapping 1:1 ═══
    if len(alive) >= n:
        # هر اکانت به instance مخصوص خودش
        mapping = {}
        for i, acc in enumerate(accounts):
            a = alive[i]
            mapping[acc["phone"]] = {
                "source": "warp",
                "proxy_type": "socks5",
                "addr": "127.0.0.1",
                "port": a["port"],
                "ip": a["ip"],
            }
        log(f"✅ 1:1 mapping: {len(mapping)} اکانت")
    else:
        # اگه کم بود، round-robin
        proxies = [{"source": "warp", "proxy_type": "socks5",
                    "addr": "127.0.0.1", "port": a["port"], "ip": a["ip"]}
                   for a in alive]
        mapping = {acc["phone"]: proxies[i % len(proxies)]
                   for i, acc in enumerate(accounts)}
        log(f"✅ round-robin: {len(mapping)} اکانت / {len(proxies)} proxy")

    MAP.write_text(json.dumps(mapping, indent=2))

    # ═══ آمار ═══
    log(f"\n{'═'*60}")
    log(f"  🌐 IP یگانه: {len(ips)}")
    log(f"  🔌 alive: {len(alive)}")
    log(f"  📊 mapping: {len(mapping)}")
    log(f"{'═'*60}")


if __name__ == "__main__":
    main()
