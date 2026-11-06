"""WARP Farm — manager خودکار 118 instance"""
import json, subprocess, time, shutil, re, random, os
from pathlib import Path
from datetime import datetime

POOL = Path("/root/tg_master_bot/proxies/warp_pool")
STATE = Path("/root/tg_master_bot/proxies/healthy_ports.json")
MAP = Path("/root/tg_master_bot/proxies/account_proxy.json")
LOG = Path("/root/tg_master_bot/logs/warp_farm.log")

TARGET = 118
MIN_ALIVE = 100
CYCLE = 30
NEW_COOLDOWN = 60
FAIL_MAX = 3
TIMEOUT = 5

ENDPOINTS = []
for base in ["162.159.192", "162.159.193", "188.114.96", "188.114.97", "188.114.98", "188.114.99"]:
    for i in range(1, 7):
        ENDPOINTS.append(f"{base}.{i}:2408")
ENDPOINTS += ["engage.cloudflareclient.com:2408", "162.159.204.1:894"]

_fail = {}
_last_new = 0
_last_redist = 0


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


def get_port(c):
    try:
        for l in c.read_text().splitlines():
            if "BindAddress" in l:
                return int(l.split(":")[-1].strip())
    except Exception:
        pass
    return None


def test(port, t=TIMEOUT):
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
    time.sleep(3)


def create(port, idx):
    d = POOL / f"w_{port}"
    if d.exists():
        kill(d); shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(["wgcf", "register", "--accept-tos"],
                       cwd=d, capture_output=True, timeout=20)
        subprocess.run(["wgcf", "generate"], cwd=d,
                       capture_output=True, timeout=20)
        profile = d / "wgcf-profile.conf"
        if not profile.exists():
            shutil.rmtree(d, ignore_errors=True); return None
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


def redist_disabled():
    global _last_redist
    _last_redist = time.time()
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
        import sys
        sys.path.insert(0, "/root/tg_master_bot")
        from models import database as db
        db.init_db()
        accounts = db.get_all_accounts()
        mapping = {acc["phone"]: proxies[i % len(proxies)]
                   for i, acc in enumerate(accounts)}
        MAP.write_text(json.dumps(mapping, indent=2))
        log(f"  📊 redist: {len(accounts)}/{len(proxies)}")
    except Exception as e:
        log(f"  ⚠️ {e}")


def cycle():
    global _last_new

    alive = []
    ips = {}
    dead = 0

    for d in sorted(POOL.glob("w_*")):
        if not d.is_dir(): continue
        conf = d / "wireproxy.conf"
        if not conf.exists(): continue
        port = get_port(conf)
        if not port: continue

        if not is_run(d):
            log(f"  🔄 restart {port}")
            restart(d)

        ip = test(port)
        if ip:
            _fail[port] = 0
            alive.append({"port": port, "ip": ip})
            ips.setdefault(ip, []).append(port)
        else:
            _fail[port] = _fail.get(port, 0) + 1
            if _fail[port] >= FAIL_MAX:
                log(f"  💀 recreate {port}")
                idx = port - 40001
                res = create(port, idx)
                if res:
                    alive.append(res)
                    ips.setdefault(res["ip"], []).append(res["port"])
                dead += 1
                _fail[port] = 0

    # ═══ ساخت جدید اگه کم داریم ═══
    now = time.time()
    if len(alive) < MIN_ALIVE and now - _last_new >= NEW_COOLDOWN:
        _last_new = now
        used = set(a["port"] for a in alive)
        nxt = 40001
        while nxt in used:
            nxt += 1
        idx = nxt - 40001
        log(f"  🔨 new {nxt} | alive:{len(alive)}")
        res = create(nxt, idx)
        if res:
            alive.append(res)
            ips.setdefault(res["ip"], []).append(res["port"])

    STATE.write_text(json.dumps({
        "updated_at": datetime.now().isoformat(),
        "unique_ips": len(ips),
        "total_alive": len(alive),
        "ip_to_ports": ips,
        "port_to_ip": {str(a["port"]): a["ip"] for a in alive},
    }, indent=2))

    # redist هر 2 دقیقه یا اگه تعداد عوض شد
    old = getattr(cycle, "_last", -1)
    if len(alive) != old or dead > 0 or now - _last_redist > 120:
        # redist()  # disabled
        cycle._last = len(alive)

    return len(ips), len(alive), dead


def main():
    log("═" * 50)
    log("🌾 WARP Farm (118)")
    log(f"   TARGET: {TARGET} | CYCLE: {CYCLE}s")
    log("═" * 50)

    while True:
        try:
            t0 = time.time()
            u, t, d = cycle()
            log(f"🔄 {u} IP | {t} alive | {d} recreate | {time.time()-t0:.1f}s")
        except Exception as e:
            log(f"❌ {type(e).__name__}: {e}")
        time.sleep(CYCLE)


if __name__ == "__main__":
    main()
