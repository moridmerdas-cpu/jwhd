"""
WARP Pool Manager — نسخه نهایی
- همیشه 5-10 instance زنده
- همه alive توی account_proxy (نه فقط active)
- process مرده = restart
- IP تکراری = نگه‌داشتن (fingerprint متفاوت)
- تلاش IP جدید هر 5 دقیقه
"""
import json, subprocess, time, shutil, re, random, os
from pathlib import Path
from datetime import datetime

POOL = Path("/root/tg_master_bot/proxies/warp_pool")
STATE_FILE = Path("/root/tg_master_bot/proxies/healthy_ports.json")
MAP_FILE = Path("/root/tg_master_bot/proxies/account_proxy.json")
LOG_FILE = Path("/root/tg_master_bot/logs/warp_pool.log")

# ═══ تنظیمات ═══
TARGET_ALIVE = 8          # هدف: 8 instance زنده
MIN_ALIVE = 5             # حداقل: 5 instance
MAX_ALIVE = 12            # سقف: 12
CHECK_INTERVAL = 15       # هر 15s چک
NEW_IP_COOLDOWN = 180     # هر 3 دقیقه تلاش جدید
TEST_TIMEOUT = 4
FAIL_THRESHOLD = 3

ENDPOINTS = [
    "162.159.192.1:2408", "162.159.192.2:2408", "162.159.192.3:2408",
    "162.159.192.4:2408", "162.159.192.5:2408",
    "162.159.193.1:2408", "162.159.193.2:2408",
    "188.114.96.1:2408", "188.114.96.2:2408",
    "188.114.97.1:2408", "188.114.97.2:2408",
    "188.114.98.1:2408", "188.114.99.1:2408",
    "engage.cloudflareclient.com:2408",
    "engage.cloudflareclient.com:500",
    "162.159.204.1:894",
]

_FAIL = {}
_last_new = 0
_last_redistribute = 0


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def get_port(c):
    try:
        for l in c.read_text().splitlines():
            if "BindAddress" in l:
                return int(l.split(":")[-1].strip())
    except Exception:
        pass
    return None


def test(port, t=TEST_TIMEOUT):
    try:
        r = subprocess.run(["curl", "-s", "--max-time", str(t),
                          "-x", f"socks5h://127.0.0.1:{port}",
                          "https://api.ipify.org"],
                         capture_output=True, text=True, timeout=t+3)
        ip = r.stdout.strip()
        if ip and ip.count(".") == 3 and len(ip) < 20:
            return ip
    except Exception:
        pass
    return None


def is_running(d):
    pf = d / "wireproxy.pid"
    if not pf.exists(): return False
    try:
        os.kill(int(pf.read_text().strip()), 0)
        return True
    except Exception:
        return False


def kill_inst(d):
    try:
        if is_running(d):
            os.kill(int((d / "wireproxy.pid").read_text()), 9)
    except Exception:
        pass
    subprocess.run(["pkill", "-9", "-f", str(d)], capture_output=True)


def restart_wp(d):
    lf = open(d / "wireproxy.log", "a")
    p = subprocess.Popen(["wireproxy", "--config", "wireproxy.conf"],
                         cwd=d, stdout=lf, stderr=subprocess.STDOUT)
    (d / "wireproxy.pid").write_text(str(p.pid))
    time.sleep(3)


def create_instance(port, ep):
    d = POOL / f"w_{port}"
    if d.exists():
        kill_inst(d)
        shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True, exist_ok=True)
    try:
        r = subprocess.run(["wgcf", "register", "--accept-tos"],
                           cwd=d, capture_output=True, timeout=20)
        if r.returncode != 0:
            shutil.rmtree(d, ignore_errors=True); return None
        r = subprocess.run(["wgcf", "generate"], cwd=d,
                           capture_output=True, timeout=20)
        if r.returncode != 0:
            shutil.rmtree(d, ignore_errors=True); return None

        profile = d / "wgcf-profile.conf"
        if not profile.exists():
            shutil.rmtree(d, ignore_errors=True); return None

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

        for _ in range(3):
            ip = test(port)
            if ip:
                return {"dir": d, "port": port, "ip": ip}
            time.sleep(2)

        kill_inst(d)
        shutil.rmtree(d, ignore_errors=True)
        return None
    except Exception:
        try:
            kill_inst(d)
            shutil.rmtree(d, ignore_errors=True)
        except Exception:
            pass
        return None


def redistribute(all_alive):
    """همه alive → account_proxy"""
    global _last_redistribute
    _last_redistribute = time.time()

    try:
        if not all_alive:
            return
        proxies = [{"source": "warp", "proxy_type": "socks5",
                    "addr": "127.0.0.1", "port": a["port"], "ip": a["ip"]}
                   for a in all_alive]
        import sys
        sys.path.insert(0, "/root/tg_master_bot")
        from models import database as db
        db.init_db()
        accounts = db.get_all_accounts()
        # round-robin
        mapping = {acc["phone"]: proxies[i % len(proxies)]
                   for i, acc in enumerate(accounts)}
        MAP_FILE.write_text(json.dumps(mapping, indent=2))
        log(f"  📊 mapping: {len(accounts)} اکانت / {len(proxies)} proxy")
    except Exception as e:
        log(f"  ⚠️ redist: {e}")


def cycle():
    global _last_new, _last_redistribute

    # ═══ ۱. rebuild alive ═══
    all_alive = []
    ips = {}
    dead = 0

    for d in sorted(POOL.glob("*")):
        if not d.is_dir(): continue
        conf = d / "wireproxy.conf"
        if not conf.exists(): continue
        port = get_port(conf)
        if not port: continue

        if not is_running(d):
            log(f"  🔄 restart {port}")
            restart_wp(d)

        ip = test(port)
        if ip:
            _FAIL[port] = 0
            all_alive.append({"port": port, "ip": ip, "dir": str(d)})
            ips.setdefault(ip, []).append(port)
        else:
            _FAIL[port] = _FAIL.get(port, 0) + 1
            if _FAIL[port] >= FAIL_THRESHOLD:
                log(f"  💀 kill {port}")
                kill_inst(d)
                shutil.rmtree(d, ignore_errors=True)
                dead += 1
                _FAIL[port] = 0

    # ═══ ۲. تلاش جدید اگه کم داریم ═══
    now = time.time()
    if len(all_alive) < TARGET_ALIVE and len(all_alive) < MAX_ALIVE:
        if now - _last_new >= NEW_IP_COOLDOWN:
            _last_new = now
            used = set(a["port"] for a in all_alive)
            for d in POOL.glob("*"):
                c = d / "wireproxy.conf"
                if c.exists():
                    p = get_port(c)
                    if p: used.add(p)
            nxt = 40001
            while nxt in used:
                nxt += 1
            ep = random.choice(ENDPOINTS)

            log(f"  🔨 try {nxt} | alive: {len(all_alive)}/{TARGET_ALIVE}")

            res = create_instance(nxt, ep)
            if res:
                all_alive.append(res)
                ips.setdefault(res["ip"], []).append(res["port"])
                if res["ip"] in ips and len(ips[res["ip"]]) > 1:
                    log(f"  🔁 IP تکراری: {res['ip']} (fingerprint جدید)")
                else:
                    log(f"  ✅ IP: {res['ip']}")

    # ═══ ۳. state ═══
    state = {
        "updated_at": datetime.now().isoformat(),
        "unique_ips": len(ips),
        "total_alive": len(all_alive),
        "ip_to_ports": ips,
        "port_to_ip": {str(a["port"]): a["ip"] for a in all_alive},
    }
    STATE_FILE.write_text(json.dumps(state, indent=2))

    # ═══ ۴. redistribute هر 90s یا اگه تعداد alive عوض شده ═══
    old_count = getattr(cycle, "_last_count", -1)
    if (len(all_alive) != old_count or
        dead > 0 or
        now - _last_redistribute > 90):
        redistribute(all_alive)
        cycle._last_count = len(all_alive)

    return len(ips), len(all_alive), dead


def main():
    log("═" * 60)
    log("🛡️ WARP Pool Manager")
    log(f"   TARGET_ALIVE: {TARGET_ALIVE} | MIN: {MIN_ALIVE} | MAX: {MAX_ALIVE}")
    log(f"   CYCLE: {CHECK_INTERVAL}s | NEW_IP: {NEW_IP_COOLDOWN}s")
    log("═" * 60)

    while True:
        try:
            t0 = time.time()
            u, t, d = cycle()
            log(f"🔄 {u} IP یگانه | {t} alive | {d} مرده | {time.time()-t0:.1f}s")
        except Exception as e:
            log(f"❌ {type(e).__name__}: {e}")
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
