"""Keepalive — فقط processها رو زنده نگه می‌داره"""
import subprocess, time, os
from pathlib import Path
from datetime import datetime

POOL = Path("/root/tg_master_bot/proxies/warp_pool")
LOG = Path("/root/tg_master_bot/logs/warp_keepalive.log")
CYCLE = 30
TIMEOUT = 4

_fail = {}


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


def is_running(d):
    pf = d / "wireproxy.pid"
    if not pf.exists():
        return False
    try:
        os.kill(int(pf.read_text().strip()), 0)
        return True
    except Exception:
        return False


def restart_wp(d):
    lf = open(d / "wireproxy.log", "a")
    p = subprocess.Popen(["wireproxy", "--config", "wireproxy.conf"],
                         cwd=d, stdout=lf, stderr=subprocess.STDOUT)
    (d / "wireproxy.pid").write_text(str(p.pid))
    time.sleep(2)


def cycle():
    total = 0
    alive = 0
    restarted = 0
    for d in sorted(POOL.glob("w_*")):
        if not d.is_dir():
            continue
        conf = d / "wireproxy.conf"
        if not conf.exists():
            continue
        port = get_port(conf)
        if not port:
            continue
        total += 1
        if not is_running(d):
            log(f"  🔄 restart {port}")
            restart_wp(d)
            restarted += 1
        ip = test(port)
        if ip:
            _fail[port] = 0
            alive += 1
        else:
            _fail[port] = _fail.get(port, 0) + 1
    return total, alive, restarted


def main():
    log("═" * 50)
    log("🔧 Keepalive (mapping دست‌نخورده)")
    log("═" * 50)
    while True:
        try:
            t0 = time.time()
            total, alive, restarted = cycle()
            log(f"🔄 {alive}/{total} alive | {restarted} restart | {time.time()-t0:.1f}s")
        except Exception as e:
            log(f"❌ {type(e).__name__}: {e}")
        time.sleep(CYCLE)


if __name__ == "__main__":
    main()
