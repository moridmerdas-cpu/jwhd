"""
WARP Master — Self-Healing IP Farm
- never kills healthy IPs
- restarts dead processes
- fresh register (delete old account)
- tries every 5 min for new IP
- target: 5-7 unique IPs
"""
import json, subprocess, time, shutil, re, random, os
from pathlib import Path
from datetime import datetime

POOL_DIR = Path("/root/tg_master_bot/proxies/warp_pool")
STATE_FILE = Path("/root/tg_master_bot/proxies/healthy_ports.json")
LOG_FILE = Path("/root/tg_master_bot/logs/warp_master.log")
MAP_FILE = Path("/root/tg_master_bot/proxies/account_proxy.json")

# ═══ تنظیمات ═══
TARGET_IPS = 5
CHECK_INTERVAL = 20
NEW_IP_COOLDOWN = 300       # 5 دقیقه بین تلاش‌ها
REGISTER_DELAY = 2          # صبر بین register
FAIL_THRESHOLD = 4
TEST_TIMEOUT = 6

ENDPOINTS = []
for base in ["162.159.192", "162.159.193", "188.114.96", "188.114.97", "188.114.98", "188.114.99"]:
    for i in range(1, 10):
        ENDPOINTS.append(f"{base}.{i}:2408")
ENDPOINTS += [
    "engage.cloudflareclient.com:2408",
    "engage.cloudflareclient.com:500",
    "engage.cloudflareclient.com:1701",
    "162.159.204.1:894",
]

_FAIL_COUNTS = {}
_LAST_NEW_ATTEMPT = 0
_LAST_REDISTRIBUTE = 0


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


def get_port(conf):
    try:
        for line in conf.read_text().splitlines():
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
            capture_output=True, text=True, timeout=timeout + 3)
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
        pid = int(pf.read_text().strip())
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def start_wireproxy(d):
    """شروع/ری‌استارت یه wireproxy"""
    conf = d / "wireproxy.conf"
    if not conf.exists():
        return False
    try:
        pf = d / "wireproxy.pid"
        # اگه process زنده‌ست، بکش
        if is_running(d):
            try:
                os.kill(int(pf.read_text()), 9)
            except Exception:
                pass
            time.sleep(0.5)

        lf = open(d / "wireproxy.log", "a")
        p = subprocess.Popen(
            ["wireproxy", "--config", "wireproxy.conf"],
            cwd=d, stdout=lf, stderr=subprocess.STDOUT)
        pf.write_text(str(p.pid))
        time.sleep(3)
        return True
    except Exception:
        return False


def kill_instance(d):
    try:
        if is_running(d):
            pf = d / "wireproxy.pid"
            os.kill(int(pf.read_text()), 9)
    except Exception:
        pass
    subprocess.run(["pkill", "-9", "-f", str(d)], capture_output=True)


def create_fresh_instance(port, endpoint):
    """ساخت instance با register کاملاً جدید (بدون account قبلی)"""
    d = POOL_DIR / f"w_{port}"
    if d.exists():
        # ═══ قبل از پاک کردن، process رو بکش ═══
        kill_instance(d)
        shutil.rmtree(d, ignore_errors=True)

    d.mkdir(parents=True, exist_ok=True)

    try:
        time.sleep(random.uniform(1, 3))

        # ═══ ۱. register (فایل‌ها رو نپاک کن، wgcf خودش fresh می‌سازه) ═══
        r = subprocess.run(["wgcf", "register", "--accept-tos"],
                           cwd=d, capture_output=True, timeout=30)
        if r.returncode != 0:
            shutil.rmtree(d, ignore_errors=True)
            return None

        # ═══ ۲. generate ═══
        r = subprocess.run(["wgcf", "generate"], cwd=d,
                           capture_output=True, timeout=30)
        if r.returncode != 0:
            shutil.rmtree(d, ignore_errors=True)
            return None

        profile = d / "wgcf-profile.conf"
        if not profile.exists():
            shutil.rmtree(d, ignore_errors=True)
            return None

        # ═══ ۳. endpoint ═══
        txt = profile.read_text()
        txt = re.sub(r'^Endpoint = .*$', f'Endpoint = {endpoint}', txt, flags=re.MULTILINE)
        if "PersistentKeepalive" not in txt:
            txt += "\nPersistentKeepalive = 25\n"
        profile.write_text(txt)

        # ═══ ۴. wireproxy config ═══
        (d / "wireproxy.conf").write_text(
            f"WGConfig = {profile}\n\n[Socks5]\nBindAddress = 127.0.0.1:{port}\n")

        # ═══ ۵. اجرا ═══
        lf = open(d / "wireproxy.log", "w")
        p = subprocess.Popen(["wireproxy", "--config", "wireproxy.conf"],
                             cwd=d, stdout=lf, stderr=subprocess.STDOUT)
        (d / "wireproxy.pid").write_text(str(p.pid))

        time.sleep(8)

        # ═══ ۶. تست (3 تلاش) ═══
        for attempt in range(3):
            ip = test_proxy(port, timeout=10)
            if ip:
                return {"dir": d, "port": port, "ip": ip}
            time.sleep(4)

        kill_instance(d)
        shutil.rmtree(d, ignore_errors=True)
        return None
    except Exception:
        try:
            kill_instance(d)
            shutil.rmtree(d, ignore_errors=True)
        except Exception:
            pass
        return None


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"ip_to_ports": {}}


def save_state(ip_to_ports):
    p2i = {}
    for ip, ports in ip_to_ports.items():
        for p in ports:
            p2i[str(p)] = ip
    STATE_FILE.write_text(json.dumps({
        "updated_at": datetime.now().isoformat(),
        "unique_ips": len(ip_to_ports),
        "ip_to_ports": ip_to_ports,
        "port_to_ip": p2i,
    }, indent=2))


def redistribute():
    global _LAST_REDISTRIBUTE
    now = time.time()
    if now - _LAST_REDISTRIBUTE < 60:
        return
    _LAST_REDISTRIBUTE = now

    try:
        state = load_state()
        ip_to_ports = state.get("ip_to_ports", {})
        if not ip_to_ports:
            return

        proxies = []
        for ip, ports in ip_to_ports.items():
            for p in ports:
                proxies.append({
                    "source": "warp",
                    "proxy_type": "socks5",
                    "addr": "127.0.0.1",
                    "port": int(p),
                    "ip": ip,
                })

        import sys
        sys.path.insert(0, "/root/tg_master_bot")
        from models import database as db
        db.init_db()
        accounts = db.get_all_accounts()

        mapping = {}
        for i, acc in enumerate(accounts):
            p = proxies[i % len(proxies)]
            mapping[acc["phone"]] = p

        MAP_FILE.write_text(json.dumps(mapping, indent=2))
        log(f"  📊 redistribute: {len(accounts)} اکانت / {len(proxies)} IP")
    except Exception as e:
        log(f"  ⚠️ redistribute: {e}")


def cycle():
    global _LAST_NEW_ATTEMPT

    # ═══ ۱. rebuild healthy از همه instanceهای زنده ═══
    healthy = {}
    dead = 0

    for d in sorted(POOL_DIR.glob("w_*")):
        if not d.is_dir():
            continue
        conf = d / "wireproxy.conf"
        if not conf.exists():
            continue
        port = get_port(conf)
        if not port:
            continue

        # ═══ ۱a. process زنده‌ست؟ اگه نه restart ═══
        if not is_running(d):
            log(f"  🔄 restart port {port}")
            start_wireproxy(d)

        # ═══ ۱b. تست واقعی ═══
        ip = test_proxy(port)
        if ip:
            _FAIL_COUNTS[port] = 0
            if ip not in healthy:
                healthy[ip] = []
            healthy[ip].append(port)
        else:
            _FAIL_COUNTS[port] = _FAIL_COUNTS.get(port, 0) + 1
            log(f"  ⚠️ port {port} fail #{_FAIL_COUNTS[port]}")
            if _FAIL_COUNTS[port] >= FAIL_THRESHOLD:
                log(f"  💀 port {port} killed after {FAIL_THRESHOLD} fails")
                kill_instance(d)
                shutil.rmtree(d, ignore_errors=True)
                dead += 1
                _FAIL_COUNTS[port] = 0

    # ═══ ۲. تلاش IP جدید ═══
    now = time.time()
    total = len([d for d in POOL_DIR.glob("w_*") if d.is_dir()])

    if (len(healthy) < TARGET_IPS and
        now - _LAST_NEW_ATTEMPT >= NEW_IP_COOLDOWN):

        _LAST_NEW_ATTEMPT = now

        # پورت آزاد
        used = set()
        for d in POOL_DIR.glob("w_*"):
            c = d / "wireproxy.conf"
            if c.exists():
                p = get_port(c)
                if p:
                    used.add(p)
        nxt = 44000
        while nxt in used:
            nxt += 1
        port = nxt

        ep = random.choice(ENDPOINTS)
        log(f"  🔨 تلاش: port {port} | ep {ep} | {len(healthy)}/{TARGET_IPS}")

        res = create_fresh_instance(port, ep)
        if res:
            if res["ip"] not in healthy:
                healthy[res["ip"]] = [port]
                log(f"  ✅ IP جدید: {res['ip']} (port {port}) | {len(healthy)}/{TARGET_IPS}")
            else:
                log(f"  🔁 تکراری {res['ip']}")

    # ═══ ۳. ذخیره ═══
    old_ips = set(load_state().get("ip_to_ports", {}).keys())
    save_state(healthy)
    new_ips = set(healthy.keys())

    # ═══ ۴. redistribute اگه تغییر کرد ═══
    if old_ips != new_ips or dead > 0:
        redistribute()

    return len(healthy), dead, total


def main():
    log("═" * 60)
    log("🚀 WARP Master — Self-Healing")
    log(f"   هدف: {TARGET_IPS} IP | چک: {CHECK_INTERVAL}s")
    log(f"   تلاش جدید: {NEW_IP_COOLDOWN}s | fail threshold: {FAIL_THRESHOLD}")
    log("═" * 60)

    while True:
        try:
            t0 = time.time()
            n, d, total = cycle()
            log(f"🔄 {n} IP / {total} کل | {d} مرده | {time.time()-t0:.1f}s")
        except Exception as e:
            log(f"❌ {type(e).__name__}: {e}")
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
