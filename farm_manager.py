"""
Farm Manager V3 — با هوش rate-limit
- فقط هر 30 دقیقه 1 تلاش برای IP جدید
- rate-limit cloudflare رو دور می‌زنه
- اگه 3 بار متوالی IP تکراری داد، 2 ساعت صبر می‌کنه
- endpoint تصادفی از 60 endpoint
"""
import json, subprocess, time, shutil, re, random
from pathlib import Path
from datetime import datetime

POOL_DIR = Path("/root/tg_master_bot/proxies/warp_pool")
STATE_FILE = Path("/root/tg_master_bot/proxies/healthy_ports.json")
LOG_FILE = Path("/root/tg_master_bot/logs/farm_manager.log")

CHECK_INTERVAL = 60            # چک IPهای موجود هر 60s
NEW_IP_INTERVAL = 1800         # ═══ هر 30 دقیقه 1 تلاش ═══
COOLDOWN_AFTER_DUP = 7200      # ═══ 3 تکراری متوالی = 2 ساعت صبر ═══
TEST_TIMEOUT = 12
FAIL_THRESHOLD = 5
TARGET_UNIQUE = 10
MAX_INSTANCES = 15

# ═══ 60 endpoint ═══
ENDPOINTS = []
for base in ["162.159.192", "162.159.193", "188.114.96", "188.114.97", "188.114.98", "188.114.99"]:
    for i in range(1, 11):
        ENDPOINTS.append(f"{base}.{i}:2408")
ENDPOINTS += [
    "engage.cloudflareclient.com:2408",
    "engage.cloudflareclient.com:500",
    "engage.cloudflareclient.com:1701",
    "engage.cloudflareclient.com:4500",
    "162.159.204.1:894",
    "162.159.204.2:894",
    "162.159.195.1:2408",
    "162.159.195.2:2408",
]

_FAIL_COUNTS = {}
_LAST_NEW_IP_ATTEMPT = 0
_CONSECUTIVE_DUPLICATES = 0
_COOLDOWN_UNTIL = 0


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


def kill_instance(d):
    try:
        pf = d / "wireproxy.pid"
        if pf.exists():
            subprocess.run(["kill", "-9", pf.read_text().strip()], capture_output=True)
    except Exception:
        pass
    subprocess.run(["pkill", "-9", "-f", str(d)], capture_output=True)


def create_instance(name, endpoint, port):
    d = POOL_DIR / name
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True, exist_ok=True)

    try:
        time.sleep(random.uniform(3, 8))

        r = subprocess.run(["wgcf", "register", "--accept-tos"],
                           cwd=d, capture_output=True, timeout=30)
        if r.returncode != 0:
            shutil.rmtree(d, ignore_errors=True)
            return None

        r = subprocess.run(["wgcf", "generate"], cwd=d,
                           capture_output=True, timeout=30)
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

        time.sleep(10)

        for attempt in range(3):
            ip = test_proxy(port, timeout=15)
            if ip:
                return {"dir": d, "port": port, "ip": ip}
            time.sleep(5)

        kill_instance(d)
        shutil.rmtree(d, ignore_errors=True)
        return None
    except Exception:
        try:
            kill_instance(d)
        except Exception:
            pass
        shutil.rmtree(d, ignore_errors=True)
        return None


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"ip_to_ports": {}, "port_to_ip": {}}


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


def redistribute_async():
    try:
        subprocess.Popen(
            ["/root/tg_env/bin/python3", "/root/tg_master_bot/distribute_accounts.py"],
            cwd="/root/tg_master_bot",
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def check_existing(state):
    current = state.get("ip_to_ports", {})
    healthy = {}
    dead = 0

    for ip, ports in current.items():
        alive = []
        for port in ports:
            inst = None
            for d in POOL_DIR.glob("warp_*"):
                conf = d / "wireproxy.conf"
                if conf.exists() and get_port(conf) == port:
                    inst = d
                    break
            if inst is None:
                continue

            test_ip = test_proxy(port)
            if test_ip:
                _FAIL_COUNTS[port] = 0
                if test_ip != ip:
                    log(f"  🔄 port {port}: {ip} → {test_ip}")
                alive.append(port)
            else:
                _FAIL_COUNTS[port] = _FAIL_COUNTS.get(port, 0) + 1
                if _FAIL_COUNTS[port] >= FAIL_THRESHOLD:
                    log(f"  💀 port {port} ({ip}) - {_FAIL_COUNTS[port]} fail")
                    kill_instance(inst)
                    shutil.rmtree(inst, ignore_errors=True)
                    dead += 1
                    _FAIL_COUNTS[port] = 0
                else:
                    alive.append(port)
        if alive:
            real_ip = test_proxy(alive[0]) or ip
            healthy[real_ip] = alive

    return healthy, dead


def try_new_ip(healthy, state):
    global _LAST_NEW_IP_ATTEMPT, _CONSECUTIVE_DUPLICATES, _COOLDOWN_UNTIL

    now = time.time()

    # cooldown active?
    if now < _COOLDOWN_UNTIL:
        remaining = int(_COOLDOWN_UNTIL - now)
        return healthy, f"cooldown ({remaining}s)"

    # زمان تلاش جدید؟
    if now - _LAST_NEW_IP_ATTEMPT < NEW_IP_INTERVAL:
        remaining = int(NEW_IP_INTERVAL - (now - _LAST_NEW_IP_ATTEMPT))
        return healthy, f"wait ({remaining}s)"

    _LAST_NEW_IP_ATTEMPT = now

    total_now = len([d for d in POOL_DIR.glob("warp_*") if d.is_dir()])
    if len(healthy) >= TARGET_UNIQUE:
        return healthy, "target reached"
    if total_now >= MAX_INSTANCES:
        return healthy, f"max instances ({MAX_INSTANCES})"

    # پورت آزاد
    used = set()
    for d in POOL_DIR.glob("warp_*"):
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
    name = f"warp_{port}"

    log(f"  🔨 تلاش: port {port} | ep {ep} | {len(healthy)}/{TARGET_UNIQUE}")

    res = create_instance(name, ep, port)

    if not res:
        log(f"  ❌ fail port {port}")
        return healthy, "failed"

    ip = res["ip"]
    if ip in healthy:
        _CONSECUTIVE_DUPLICATES += 1
        log(f"  🔁 تکراری {ip} | تکراری متوالی: {_CONSECUTIVE_DUPLICATES}")

        # اگه 3 بار متوالی تکراری → cooldown
        if _CONSECUTIVE_DUPLICATES >= 3:
            _COOLDOWN_UNTIL = now + COOLDOWN_AFTER_DUP
            log(f"  😴 {_CONSECUTIVE_DUPLICATES} تکراری متوالی → cooldown {COOLDOWN_AFTER_DUP}s")
            _CONSECUTIVE_DUPLICATES = 0

        kill_instance(res["dir"])
        shutil.rmtree(res["dir"], ignore_errors=True)
        return healthy, "duplicate"

    _CONSECUTIVE_DUPLICATES = 0
    healthy[ip] = [port]
    log(f"  ✅ IP جدید: {ip} (port {port}) | {len(healthy)}/{TARGET_UNIQUE}")
    return healthy, "new_ip"


def cycle():
    state = load_state()
    healthy, dead = check_existing(state)
    healthy, reason = try_new_ip(healthy, state)

    old_ports = set()
    for ports in state.get("ip_to_ports", {}).values():
        old_ports.update(ports)
    new_ports = set()
    for ports in healthy.values():
        new_ports.update(ports)

    save_state(healthy)

    if old_ports != new_ports or dead > 0:
        redistribute_async()
        log(f"  📊 redistribute | {len(healthy)} IP")

    return len(healthy), dead, reason


def main():
    log("═" * 60)
    log("🌾 Farm Manager V3 — صبور")
    log(f"   چک IP: {CHECK_INTERVAL}s | IP جدید: {NEW_IP_INTERVAL}s")
    log(f"   cooldown بعد 3 تکراری: {COOLDOWN_AFTER_DUP}s")
    log(f"   هدف: {TARGET_UNIQUE} IP | endpoints: {len(ENDPOINTS)}")
    log("═" * 60)

    last_check = 0
    while True:
        try:
            now = time.time()
            if now - last_check >= CHECK_INTERVAL:
                last_check = now
                t0 = time.time()
                n, d, reason = cycle()
                log(f"🔄 {n} IP | {d} مرده | {reason} | {time.time()-t0:.1f}s")
        except Exception as e:
            log(f"❌ {type(e).__name__}: {e}")
        time.sleep(10)


if __name__ == "__main__":
    main()
