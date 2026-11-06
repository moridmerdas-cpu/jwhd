"""WARP 1:1 Manager — restart مرده‌ها، حفظ mapping"""
import json, subprocess, time, shutil, re, random, os
from pathlib import Path
from datetime import datetime

POOL = Path("/root/tg_master_bot/proxies/warp_pool")
STATE = Path("/root/tg_master_bot/proxies/healthy_ports.json")
MAP = Path("/root/tg_master_bot/proxies/account_proxy.json")
LOG = Path("/root/tg_master_bot/logs/warp_1to1.log")

CYCLE = 30
FAIL_MAX = 3
TIMEOUT = 5

ENDPOINTS = []
for base in ["162.159.192", "162.159.193", "188.114.96", "188.114.97"]:
    for i in range(1, 6):
        ENDPOINTS.append(f"{base}.{i}:2408")
ENDPOINTS += ["engage.cloudflareclient.com:2408", "162.159.204.1:894"]

_fail = {}


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
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


def restart(d):
    try:
        lf = open(d / "wireproxy.log", "a")
        p = subprocess.Popen(["wireproxy", "--config", "wireproxy.conf"],
                             cwd=d, stdout=lf, stderr=subprocess.STDOUT)
        (d / "wireproxy.pid").write_text(str(p.pid))
        time.sleep(3)
        return True
    except Exception:
        return False


def recreate(port, idx):
    """ساخت مجدد"""
    d = POOL / f"w_{port}"
    if d.exists():
        subprocess.run(["pkill", "-9", "-f", str(d)], capture_output=True)
        shutil.rmtree(d, ignore_errors=True)
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


def cycle():
    alive = []
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
        else:
            _fail[port] = _fail.get(port, 0) + 1
            if _fail[port] >= FAIL_MAX:
                log(f"  💀 recreate {port}")
                idx = port - 40001
                res = recreate(port, idx)
                if res:
                    alive.append(res)
                    dead += 1
                _fail[port] = 0

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

    # mapping حفظ شود (فقط اگه اکانت جدید داشتیم)
    if MAP.exists():
        try:
            mapping = json.loads(MAP.read_text())
            # آپدیت IP اگه پورت هنوز هست
            port_to_ip = {str(a["port"]): a["ip"] for a in alive}
            changed = False
            for phone, info in mapping.items():
                p = str(info.get("port"))
                if p in port_to_ip and info.get("ip") != port_to_ip[p]:
                    info["ip"] = port_to_ip[p]
                    changed = True
            if changed:
                MAP.write_text(json.dumps(mapping, indent=2))
        except Exception as e:
            log(f"  ⚠️ {e}")

    return len(ips), len(alive), dead


def main():
    log("═" * 50)
    log("🔧 WARP 1:1 Manager")
    log(f"   CYCLE: {CYCLE}s")
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
