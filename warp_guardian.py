"""
WARP Guardian — نسخه دیروز (کارکرده)
- هر 30s چک
- هدف: 5 IP
- فقط process مرده رو restart می‌کنه
- IP سالم رو نمی‌کشه
- register جدید تدریجی
"""
import json, subprocess, time, shutil, re, random, os
from pathlib import Path
from datetime import datetime

POOL_DIR = Path("/root/tg_master_bot/proxies/warp_pool")
STATE_FILE = Path("/root/tg_master_bot/proxies/healthy_ports.json")
LOG_FILE = Path("/root/tg_master_bot/logs/warp_guardian.log")

CYCLE_SECONDS = 20
TEST_TIMEOUT = 4
FAIL_THRESHOLD = 3
TARGET_UNIQUE = 7

ENDPOINTS = [
    "162.159.192.1:2408", "162.159.192.2:2408", "162.159.192.3:2408",
    "162.159.192.4:2408", "162.159.192.5:2408",
    "162.159.193.1:2408", "162.159.193.2:2408", "162.159.193.3:2408",
    "162.159.195.1:2408", "162.159.195.2:2408",
    "188.114.96.1:2408", "188.114.96.2:2408", "188.114.96.3:2408",
    "188.114.97.1:2408", "188.114.97.2:2408", "188.114.97.3:2408",
    "188.114.98.1:2408", "188.114.99.1:2408",
    "162.159.204.1:894", "162.159.204.2:894",
    "engage.cloudflareclient.com:2408",
    "engage.cloudflareclient.com:500",
]

_FAIL_COUNTS = {}


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
        os.kill(int(pf.read_text().strip()), 0)
        return True
    except Exception:
        return False


def kill_instance(d):
    try:
        if is_running(d):
            os.kill(int((d / "wireproxy.pid").read_text()), 9)
    except Exception:
        pass
    subprocess.run(["pkill", "-9", "-f", str(d)], capture_output=True)


def restart_instance(d):
    """restart فقط اگه config هست"""
    conf = d / "wireproxy.conf"
    if not conf.exists():
        return False
    try:
        lf = open(d / "wireproxy.log", "a")
        p = subprocess.Popen(
            ["wireproxy", "--config", "wireproxy.conf"],
            cwd=d, stdout=lf, stderr=subprocess.STDOUT)
        (d / "wireproxy.pid").write_text(str(p.pid))
        time.sleep(3)
        return True
    except Exception:
        return False


def create_instance(name, endpoint, port):
    d = POOL_DIR / name
    if d.exists():
        kill_instance(d)
        shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True, exist_ok=True)

    try:
        r = subprocess.run(["wgcf", "register", "--accept-tos"],
                           cwd=d, capture_output=True, timeout=25)
        if r.returncode != 0:
            shutil.rmtree(d, ignore_errors=True)
            return None

        r = subprocess.run(["wgcf", "generate"],
                           cwd=d, capture_output=True, timeout=25)
        if r.returncode != 0:
            shutil.rmtree(d, ignore_errors=True)
            return None

        profile = d / "wgcf-profile.conf"
        if not profile.exists():
            shutil.rmtree(d, ignore_errors=True)
            return None

        txt = profile.read_text()
        txt = re.sub(r'^Endpoint = .*$', f'Endpoint = {endpoint}', txt, flags=re.MULTILINE)
        if "PersistentKeepalive" not in txt:
            txt += "\nPersistentKeepalive = 25\n"
        profile.write_text(txt)

        (d / "wireproxy.conf").write_text(
            f"WGConfig = {profile}\n\n[Socks5]\nBindAddress = 127.0.0.1:{port}\n")

        lf = open(d / "wireproxy.log", "w")
        p = subprocess.Popen(["wireproxy", "--config", "wireproxy.conf"],
                             cwd=d, stdout=lf, stderr=subprocess.STDOUT)
        (d / "wireproxy.pid").write_text(str(p.pid))

        time.sleep(6)

        for _ in range(3):
            ip = test_proxy(port)
            if ip:
                return {"dir": d, "port": port, "ip": ip}
            time.sleep(2)

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


def save_state(h):
    p2i = {}
    for ip, ports in h.items():
        for p in ports:
            p2i[str(p)] = ip
    STATE_FILE.write_text(json.dumps({
        "updated_at": datetime.now().isoformat(),
        "unique_ips": len(h),
        "ip_to_ports": h,
        "port_to_ip": p2i,
    }, indent=2))


def redistribute():
    try:
        h = load_state().get("ip_to_ports", {})
        if not h:
            return
        proxies = []
        for ip, ports in h.items():
            for p in ports:
                proxies.append({
                    "source": "warp", "proxy_type": "socks5",
                    "addr": "127.0.0.1", "port": int(p), "ip": ip,
                })
        import sys
        sys.path.insert(0, "/root/tg_master_bot")
        from models import database as db
        db.init_db()
        accounts = db.get_all_accounts()
        mapping = {}
        for i, acc in enumerate(accounts):
            mapping[acc["phone"]] = proxies[i % len(proxies)]
        Path("/root/tg_master_bot/proxies/account_proxy.json").write_text(
            json.dumps(mapping, indent=2))
    except Exception:
        pass


def cycle():
    state = load_state()
    current = state.get("ip_to_ports", {})
    healthy = {}
    dead = 0

    # ═══ ۱. چک همه instanceها ═══
    for d in sorted(POOL_DIR.glob("w_*")) + sorted(POOL_DIR.glob("warp_*")):
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
            restart_instance(d)

        # تست واقعی
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
                log(f"  💀 port {port} killed")
                kill_instance(d)
                shutil.rmtree(d, ignore_errors=True)
                dead += 1
                _FAIL_COUNTS[port] = 0

    # ═══ ۲. تلاش جدید (اگه کمتر از target) ═══
    total = len([d for d in POOL_DIR.glob("w_*") if d.is_dir()]) + \
            len([d for d in POOL_DIR.glob("warp_*") if d.is_dir()])

    if len(healthy) < TARGET_UNIQUE and total < 25:
        used = set()
        for d in list(POOL_DIR.glob("w_*")) + list(POOL_DIR.glob("warp_*")):
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
        name = f"warp_g_{int(time.time())%100000}"

        log(f"  🔨 try: port {port} | ep {ep} | {len(healthy)}/{TARGET_UNIQUE}")

        res = create_instance(name, ep, port)
        if res:
            if res["ip"] not in healthy:
                healthy[res["ip"]] = [port]
                log(f"  ✅ IP جدید: {res['ip']} | {len(healthy)}/{TARGET_UNIQUE}")
            else:
                log(f"  🔁 تکراری {res['ip']}")
                kill_instance(res["dir"])
                shutil.rmtree(res["dir"], ignore_errors=True)

    # ═══ ۳. ذخیره + redistribute ═══
    old_ports = set()
    for ports in current.values():
        old_ports.update(ports)
    new_ports = set()
    for ports in healthy.values():
        new_ports.update(ports)

    save_state(healthy)

    if old_ports != new_ports or dead > 0:
        redistribute()
        log(f"  📊 redistributed | {len(healthy)} IP")

    return len(healthy), dead


def main():
    log("═" * 60)
    log("🚀 WARP Guardian — نسخه دیروز")
    log(f"   CYCLE: {CYCLE_SECONDS}s | TARGET: {TARGET_UNIQUE} IP")
    log("═" * 60)

    while True:
        try:
            t0 = time.time()
            n, d = cycle()
            log(f"🔄 {n} IP | {d} مرده | {time.time()-t0:.1f}s")
        except Exception as e:
            log(f"❌ {type(e).__name__}: {e}")
        time.sleep(CYCLE_SECONDS)


if __name__ == "__main__":
    main()
