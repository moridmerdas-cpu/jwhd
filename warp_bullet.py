"""
WARP Bulletproof — همیشه زاپاس آماده
- حداقل 5 instance زنده
- 2-3 active + 3+ standby
- سوییچ فوری وقتی IP می‌میره
- swap شیفت 60-120s
- redistribute خودکار در هر تغییر
"""
import json, subprocess, time, shutil, re, random, os
from pathlib import Path
from datetime import datetime

POOL_DIR = Path("/root/tg_master_bot/proxies/warp_pool")
STATE_FILE = Path("/root/tg_master_bot/proxies/healthy_ports.json")
MAP_FILE = Path("/root/tg_master_bot/proxies/account_proxy.json")
LOG_FILE = Path("/root/tg_master_bot/logs/warp_bullet.log")

# ═══ تنظیمات ═══
MIN_ALIVE = 5             # حداقل instance زنده (نه IP یکتا)
MIN_UNIQUE = 2            # حداقل IP یکتا
TARGET_UNIQUE = 7         # هدف IP یکتا
CHECK_INTERVAL = 15       # هر 15s چک
NEW_IP_COOLDOWN = 90      # هر 90s تلاش IP جدید
TEST_TIMEOUT = 4
FAIL_THRESHOLD = 3

ENDPOINTS = []
for base in ["162.159.192", "162.159.193", "188.114.96", "188.114.97", "188.114.98", "188.114.99"]:
    for i in range(1, 8):
        ENDPOINTS.append(f"{base}.{i}:2408")
ENDPOINTS += [
    "engage.cloudflareclient.com:2408",
    "engage.cloudflareclient.com:500",
    "engage.cloudflareclient.com:1701",
    "162.159.204.1:894",
]

_FAIL_COUNTS = {}
_LAST_NEW_ATTEMPT = 0


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
        for line in c.read_text().splitlines():
            if "BindAddress" in line:
                return int(line.split(":")[-1].strip())
    except Exception:
        pass
    return None


def test_proxy(port, timeout=TEST_TIMEOUT):
    try:
        r = subprocess.run(
            ["curl", "-s", "--max-time", str(timeout),
             "-x", f"socks5h://127.0.0.1:{port}",
             "https://api.ipify.org"],
            capture_output=True, text=True, timeout=timeout + 2)
        ip = r.stdout.strip()
        if ip and ip.count(".") == 3 and len(ip) < 20:
            return ip
    except Exception:
        pass
    return None


def is_running(d):
    pf = d / "wireproxy.pid"
    if not pf.exists():
        return False
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
    """restart بدون از دست دادن config"""
    lf = open(d / "wireproxy.log", "a")
    p = subprocess.Popen(["wireproxy", "--config", "wireproxy.conf"],
                         cwd=d, stdout=lf, stderr=subprocess.STDOUT)
    (d / "wireproxy.pid").write_text(str(p.pid))
    time.sleep(2)
    return True


def create_instance(name, ep, port):
    d = POOL_DIR / name
    if d.exists():
        kill_inst(d)
        shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True, exist_ok=True)

    try:
        r = subprocess.run(["wgcf", "register", "--accept-tos"],
                           cwd=d, capture_output=True, timeout=20)
        if r.returncode != 0:
            shutil.rmtree(d, ignore_errors=True)
            return None

        r = subprocess.run(["wgcf", "generate"],
                           cwd=d, capture_output=True, timeout=20)
        if r.returncode != 0:
            shutil.rmtree(d, ignore_errors=True)
            return None

        profile = d / "wgcf-profile.conf"
        if not profile.exists():
            shutil.rmtree(d, ignore_errors=True)
            return None

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
            ip = test_proxy(port)
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
    """توزیع با standby — همه instanceهای زنده در نظر گرفته می‌شن"""
    try:
        # همه پورت‌های زنده
        proxies = []
        for item in all_alive:
            proxies.append({
                "source": "warp", "proxy_type": "socks5",
                "addr": "127.0.0.1", "port": item["port"], "ip": item["ip"],
            })

        if not proxies:
            return

        import sys
        sys.path.insert(0, "/root/tg_master_bot")
        from models import database as db
        db.init_db()
        accounts = db.get_all_accounts()

        mapping = {}
        for i, acc in enumerate(accounts):
            mapping[acc["phone"]] = proxies[i % len(proxies)]

        MAP_FILE.write_text(json.dumps(mapping, indent=2))
        log(f"  📊 redistribute: {len(accounts)} اکانت / {len(proxies)} proxy")
    except Exception as e:
        log(f"  ⚠️ redistribute: {e}")


def cycle():
    global _LAST_NEW_ATTEMPT

    # ═══ ۱. rebuild alive از همه instanceها ═══
    all_alive = []       # [{port, ip, dir}]
    unique_ips = {}      # ip → [port, ...]
    dead = 0

    for d in sorted(POOL_DIR.glob("*")):
        if not d.is_dir():
            continue
        conf = d / "wireproxy.conf"
        if not conf.exists():
            continue
        port = get_port(conf)
        if not port:
            continue

        # process مرده؟ restart
        if not is_running(d):
            log(f"  🔄 restart port {port}")
            restart_wp(d)

        # تست
        ip = test_proxy(port)
        if ip:
            _FAIL_COUNTS[port] = 0
            all_alive.append({"port": port, "ip": ip, "dir": d})
            unique_ips.setdefault(ip, []).append(port)
        else:
            _FAIL_COUNTS[port] = _FAIL_COUNTS.get(port, 0) + 1
            if _FAIL_COUNTS[port] >= FAIL_THRESHOLD:
                log(f"  💀 kill port {port} (fail {FAIL_THRESHOLD}x)")
                kill_inst(d)
                shutil.rmtree(d, ignore_errors=True)
                dead += 1
                _FAIL_COUNTS[port] = 0

    # ═══ ۲. ساخت instance جدید ═══
    now = time.time()
    need_more = (len(all_alive) < MIN_ALIVE) or (len(unique_ips) < TARGET_UNIQUE)
    can_try = now - _LAST_NEW_ATTEMPT >= NEW_IP_COOLDOWN
    not_too_many = len(all_alive) < 8

    if need_more and can_try and not_too_many:
        _LAST_NEW_ATTEMPT = now

        used = set(p["port"] for p in all_alive)
        for d in POOL_DIR.glob("*"):
            c = d / "wireproxy.conf"
            if c.exists():
                p = get_port(c)
                if p:
                    used.add(p)

        nxt = 40001
        while nxt in used:
            nxt += 1
        port = nxt
        ep = random.choice(ENDPOINTS)
        name = f"w_{port}"

        log(f"  🔨 try: {port} | IP یگانه: {len(unique_ips)}/{TARGET_UNIQUE} | کل: {len(all_alive)}")

        res = create_instance(name, ep, port)
        if res:
            if res["ip"] not in unique_ips:
                all_alive.append(res)
                unique_ips.setdefault(res["ip"], []).append(res["port"])
                log(f"  ✅ IP جدید: {res['ip']} | یگانه: {len(unique_ips)}")
            else:
                # ═══ IP تکراری → بکش، نگه ندار ═══
                kill_inst(res["dir"])
                shutil.rmtree(res["dir"], ignore_errors=True)
                log(f"  🔁 IP تکراری: {res['ip']} — پاک شد")

    # ═══ ۳. ذخیره state ═══
    state = {
        "updated_at": datetime.now().isoformat(),
        "unique_ips": len(unique_ips),
        "total_alive": len(all_alive),
        "ip_to_ports": {ip: ports for ip, ports in unique_ips.items()},
        "port_to_ip": {str(item["port"]): item["ip"] for item in all_alive},
    }
    STATE_FILE.write_text(json.dumps(state, indent=2))

    # ═══ ۴. redistribute (اگه تغییر کرد) ═══
    if dead > 0 or len(all_alive) != getattr(cycle, "_last_count", -1):
        redistribute(all_alive)
        cycle._last_count = len(all_alive)

    return len(unique_ips), len(all_alive), dead


def main():
    log("═" * 60)
    log("🛡️ WARP Bulletproof")
    log(f"   MIN_ALIVE: {MIN_ALIVE} | TARGET_UNIQUE: {TARGET_UNIQUE}")
    log(f"   CYCLE: {CHECK_INTERVAL}s | NEW_IP: {NEW_IP_COOLDOWN}s")
    log("═" * 60)

    while True:
        try:
            t0 = time.time()
            u, t, d = cycle()
            log(f"🔄 {u} IP یگانه / {t} کل | {d} مرده | {time.time()-t0:.1f}s")
        except Exception as e:
            log(f"❌ {type(e).__name__}: {e}")
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
