"""Build Farm — تا 120 instance با صبر بین registerها"""
import subprocess, time, re, random, json, sys, os, shutil
from pathlib import Path
from datetime import datetime

sys.path.insert(0, '/root/tg_master_bot')
from models import database as db

POOL = Path("/root/tg_master_bot/proxies/warp_pool")
STATE = Path("/root/tg_master_bot/proxies/healthy_ports.json")
MAP = Path("/root/tg_master_bot/proxies/account_proxy.json")
LOG = Path("/root/tg_master_bot/logs/build_farm.log")

TARGET = 120

# 60 endpoint متفاوت
ENDPOINTS = []
for base in ["162.159.192", "162.159.193", "188.114.96", "188.114.97", "188.114.98", "188.114.99"]:
    for i in range(1, 11):
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


def is_run(d):
    pf = d / "wireproxy.pid"
    if not pf.exists(): return False
    try:
        os.kill(int(pf.read_text().strip()), 0)
        return True
    except Exception:
        return False


def kill(d):
    try:
        if is_run(d):
            os.kill(int((d / "wireproxy.pid").read_text()), 9)
    except Exception:
        pass
    subprocess.run(["pkill", "-9", "-f", str(d)], capture_output=True)


def restart(d):
    lf = open(d / "wireproxy.log", "a")
    p = subprocess.Popen(["wireproxy", "--config", "wireproxy.conf"],
                         cwd=d, stdout=lf, stderr=subprocess.STDOUT)
    (d / "wireproxy.pid").write_text(str(p.pid))
    time.sleep(2)


def create(port, idx):
    """ساخت یه instance"""
    d = POOL / f"w_{port}"
    if d.exists():
        kill(d)
        shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True, exist_ok=True)
    try:
        r = subprocess.run(["wgcf", "register", "--accept-tos"],
                           cwd=d, capture_output=True, timeout=25)
        if r.returncode != 0:
            shutil.rmtree(d, ignore_errors=True)
            return None
        r = subprocess.run(["wgcf", "generate"], cwd=d,
                           capture_output=True, timeout=25)
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
        time.sleep(5)

        # ۳ تلاش تست
        for _ in range(3):
            ip = test(port)
            if ip:
                return {"port": port, "ip": ip}
            time.sleep(2)

        return None
    except Exception:
        return None


def build():
    """ساخت تا رسیدن به TARGET"""
    db.init_db()
    accounts = db.get_all_accounts()
    n_acc = len(accounts)

    # instanceهای موجود
    existing = set()
    for d in POOL.glob("w_*"):
        if not d.is_dir(): continue
        c = d / "wireproxy.conf"
        if not c.exists(): continue
        for line in c.read_text().splitlines():
            if "BindAddress" in line:
                p = int(line.split(":")[-1].strip())
                existing.add(p)
                break

    log(f"═" * 60)
    log(f"🚀 Build Farm → target {TARGET}")
    log(f"   موجود: {len(existing)} | اکانت: {n_acc}")
    log(f"═" * 60)

    # شمارش
    ok = 0
    fail = 0
    port = 40001

    while True:
        # چند instance زنده داریم؟
        alive_count = 0
        for d in POOL.glob("w_*"):
            if not d.is_dir(): continue
            if is_run(d):
                alive_count += 1

        # اگه به target رسیدیم
        if alive_count >= TARGET:
            log(f"\n🎉 به هدف رسیدیم: {alive_count}/{TARGET}")
            break

        # پورت بعدی
        while port in existing:
            port += 1
        idx = port - 40001

        # ساخت
        res = create(port, idx)
        if res:
            existing.add(port)
            ok += 1
            log(f"  ✅ [{ok}/{TARGET-30}] port {port} → {res['ip']} | alive: {alive_count+1}")
            time.sleep(5)   # صبر بین registerهای موفق
        else:
            fail += 1
            log(f"  ❌ port {port} fail #{fail}")
            # اگه 10 تا پشت سر هم fail خورد، صبر بیشتر
            if fail % 10 == 0:
                log(f"  😴 10 fail متوالی → صبر 60s")
                time.sleep(60)
            else:
                time.sleep(15)  # صبر بین failها

        port += 1

        # هر 5 instance، state رو ذخیره کن
        if ok % 5 == 0 and ok > 0:
            save_state()

    save_state()
    redist()


def save_state():
    """ذخیره state"""
    alive = []
    for d in POOL.glob("w_*"):
        if not d.is_dir(): continue
        c = d / "wireproxy.conf"
        if not c.exists(): continue
        port = None
        for line in c.read_text().splitlines():
            if "BindAddress" in line:
                port = int(line.split(":")[-1].strip())
                break
        if not port: continue
        if not is_run(d): continue
        ip = test(port, t=3)
        if ip:
            alive.append({"port": port, "ip": ip})

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


def redist():
    """توزیع round-robin"""
    try:
        state = json.loads(STATE.read_text())
        alive = []
        for ip, ports in state.get("ip_to_ports", {}).items():
            for p in ports:
                alive.append({"port": p, "ip": ip})
        if not alive: return
        proxies = [{"source": "warp", "proxy_type": "socks5",
                    "addr": "127.0.0.1", "port": a["port"], "ip": a["ip"]}
                   for a in alive]
        from models import database as db
        db.init_db()
        accounts = db.get_all_accounts()
        mapping = {acc["phone"]: proxies[i % len(proxies)]
                   for i, acc in enumerate(accounts)}
        MAP.write_text(json.dumps(mapping, indent=2))
        log(f"  📊 redist: {len(accounts)}/{len(proxies)}")
    except Exception as e:
        log(f"  ⚠️ redist: {e}")


if __name__ == "__main__":
    build()
