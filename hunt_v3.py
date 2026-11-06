"""
Hunt V3 — جامع، تمیز، فقط سالم‌ها رو نگه‌دار
- WARP: تدریجی (صبر بین register)
- Public: از 12 منبع، تست کامل
- هدف: 4+ WARP + 100+ Public
- فقط IP یگانه و سالم
"""
import subprocess, time, shutil, re, random, json, socket, os
import asyncio, aiohttp
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

POOL_DIR = Path("/root/tg_master_bot/proxies/warp_pool")
WARP_STATE = Path("/root/tg_master_bot/proxies/healthy_ports.json")
PUBLIC_STATE = Path("/root/tg_master_bot/proxies/public_proxies.json")
LOG_FILE = Path("/root/tg_master_bot/logs/hunt.log")

# ═══ اهداف ═══
TARGET_WARP = 4
TARGET_PUBLIC = 100
DURATION_MIN = 60   # حداکثر یک ساعت تلاش

# ═══ WARP endpoints ═══
WARP_ENDPOINTS = []
for base in ["162.159.192", "162.159.193", "188.114.96", "188.114.97", "188.114.98", "188.114.99"]:
    for i in range(1, 6):
        WARP_ENDPOINTS.append(f"{base}.{i}:2408")
WARP_ENDPOINTS += [
    "engage.cloudflareclient.com:2408",
    "engage.cloudflareclient.com:500",
    "162.159.204.1:894",
]

# ═══ Public sources ═══
PUBLIC_SOURCES = [
    ("https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&protocol=socks5&timeout=3000&format=text&proxy_format=ipport", "socks5"),
    ("https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&protocol=http&timeout=3000&format=text&proxy_format=ipport", "http"),
    ("https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks5.txt", "socks5"),
    ("https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt", "http"),
    ("https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks5.txt", "socks5"),
    ("https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt", "http"),
    ("https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/socks5/data.txt", "socks5"),
    ("https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/http/data.txt", "http"),
    ("https://raw.githubusercontent.com/hookzof/socks5_list/master/proxy.txt", "socks5"),
    ("https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt", "http"),
    ("https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/socks5.txt", "socks5"),
    ("https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/http.txt", "http"),
]


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


# ═══════════════════════════════════════════════════
#  WARP Hunting
# ═══════════════════════════════════════════════════
def get_port(c):
    for line in c.read_text().splitlines():
        if "BindAddress" in line:
            return int(line.split(":")[-1].strip())
    return None


def test_socks(port, timeout=8):
    try:
        r = subprocess.run(
            ["curl", "-s", "--max-time", str(timeout),
             "-x", f"socks5h://127.0.0.1:{port}",
             "https://api.ipify.org"],
            capture_output=True, text=True, timeout=timeout+3)
        ip = r.stdout.strip()
        if ip and ip.count(".") == 3 and len(ip) < 20:
            return ip
    except Exception:
        pass
    return None


def kill_inst(d):
    try:
        pf = d / "wireproxy.pid"
        if pf.exists():
            os.kill(int(pf.read_text().strip()), 9)
    except Exception:
        pass
    subprocess.run(["pkill", "-9", "-f", str(d)], capture_output=True)


def create_warp(name, endpoint, port):
    d = POOL_DIR / name
    if d.exists():
        kill_inst(d)
        shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True, exist_ok=True)

    try:
        r = subprocess.run(["wgcf", "register", "--accept-tos"],
                           cwd=d, capture_output=True, timeout=30)
        if r.returncode != 0:
            shutil.rmtree(d, ignore_errors=True)
            return None

        r = subprocess.run(["wgcf", "generate"],
                           cwd=d, capture_output=True, timeout=30)
        if r.returncode != 0:
            shutil.rmtree(d, ignore_errors=True)
            return None

        profile = d / "wgcf-profile.conf"
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
        time.sleep(8)

        for _ in range(4):
            ip = test_socks(port, 12)
            if ip:
                return {"dir": str(d), "port": port, "ip": ip}
            time.sleep(4)

        kill_inst(d)
        shutil.rmtree(d, ignore_errors=True)
        return None
    except Exception as e:
        try:
            kill_inst(d)
            shutil.rmtree(d, ignore_errors=True)
        except Exception:
            pass
        return None


def hunt_warp():
    log("\n" + "=" * 60)
    log(f"🔨 WARP Hunt — هدف {TARGET_WARP} IP")
    log("=" * 60)

    warp_ips = {}   # ip → port
    try_num = 0
    start = time.time()
    deadline = start + 30 * 60  # 30 دقیقه

    while len(warp_ips) < TARGET_WARP and time.time() < deadline:
        try_num += 1
        port = 45000 + try_num
        ep = random.choice(WARP_ENDPOINTS)
        name = f"w_{port}"

        log(f"  🔨 try #{try_num}: port {port} | {len(warp_ips)}/{TARGET_WARP}")

        res = create_warp(name, ep, port)
        if not res:
            log(f"  ❌ fail")
            time.sleep(15)
            continue

        ip = res["ip"]
        if ip in warp_ips:
            log(f"  🔁 تکراری: {ip}")
            kill_inst(Path(res["dir"]))
            shutil.rmtree(res["dir"], ignore_errors=True)
            time.sleep(30)
            continue

        warp_ips[ip] = port
        log(f"  ✅ IP جدید: {ip} | {len(warp_ips)}/{TARGET_WARP}")

        if len(warp_ips) < TARGET_WARP:
            wait = random.uniform(20, 40)
            log(f"  ⏳ صبر {wait:.0f}s...")
            time.sleep(wait)

    # ذخیره
    p2i = {}
    for ip, port in warp_ips.items():
        p2i[str(port)] = ip
    WARP_STATE.write_text(json.dumps({
        "updated_at": datetime.now().isoformat(),
        "unique_ips": len(warp_ips),
        "ip_to_ports": {ip: [port] for ip, port in warp_ips.items()},
        "port_to_ip": p2i,
    }, indent=2))

    log(f"\n🎯 WARP نتیجه: {len(warp_ips)} IP")
    for ip, port in warp_ips.items():
        log(f"   {ip} → {port}")

    return warp_ips


# ═══════════════════════════════════════════════════
#  Public Proxy Hunting
# ═══════════════════════════════════════════════════
async def fetch_source(session, url, ptype):
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as r:
            if r.status != 200:
                return []
            text = await r.text()
    except Exception:
        return []

    out = []
    for line in text.split("\n"):
        line = line.strip()
        m = re.match(r'^(\d+\.\d+\.\d+\.\d+):(\d+)$', line)
        if m:
            out.append((ptype, f"{m.group(1)}:{m.group(2)}"))
    return out


async def test_public(session, ptype, proxy_str, sem, results):
    async with sem:
        try:
            url = f"{ptype}://{proxy_str}"
            async with session.get(
                "https://api.ipify.org",
                proxy=url,
                timeout=aiohttp.ClientTimeout(total=8)) as r:
                if r.status == 200:
                    ip = (await r.text()).strip()
                    if re.match(r'^\d+\.\d+\.\d+\.\d+$', ip):
                        results.append({
                            "type": ptype, "proxy": proxy_str, "exit_ip": ip
                        })
        except Exception:
            pass


async def hunt_public():
    log("\n" + "=" * 60)
    log(f"🌐 Public Hunt — هدف {TARGET_PUBLIC}")
    log("=" * 60)

    log("  📥 جمع‌آوری از منابع...")
    all_proxies = set()

    async with aiohttp.ClientSession() as session:
        tasks = [fetch_source(session, url, ptype) for url, ptype in PUBLIC_SOURCES]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    for r in results:
        if isinstance(r, list):
            for item in r:
                all_proxies.add(item)

    log(f"  📦 جمع‌آوری: {len(all_proxies)} خام")

    if not all_proxies:
        return {}

    # تست همه با concurrency 500
    log(f"  ⏳ تست {len(all_proxies)} (500 parallel)...")
    sem = asyncio.Semaphore(500)
    healthy = []

    async with aiohttp.ClientSession() as session:
        tasks = [test_public(session, pt, p, sem, healthy) for pt, p in all_proxies]
        done_count = [0]
        total = len(tasks)

        async def progress():
            while done_count[0] < total:
                await asyncio.sleep(10)
                log(f"    ... {done_count[0]}/{total} | سالم: {len(healthy)}")

        for t in tasks:
            t.add_done_callback(lambda _: done_count.__setitem__(0, done_count[0]+1))

        prog = asyncio.create_task(progress())
        await asyncio.gather(*tasks, return_exceptions=True)
        prog.cancel()

    # گروه‌بندی بر اساس IP خروجی
    by_ip = {}
    for h in healthy:
        by_ip.setdefault(h["exit_ip"], []).append(h)

    log(f"  ✅ سالم: {len(healthy)} | IP یگانه: {len(by_ip)}")

    # ذخیره (فقط IP یگانه)
    unique = []
    for ip, items in by_ip.items():
        unique.append(items[0])

    PUBLIC_STATE.write_text(json.dumps({
        "updated_at": datetime.now().isoformat(),
        "total": len(unique),
        "proxies": unique,
    }, indent=2))

    log(f"  💾 ذخیره: {len(unique)} proxy یگانه")

    return unique


# ═══════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════
def main():
    log("=" * 60)
    log("🎯 HUNT V3 — جامع")
    log(f"   WARP: {TARGET_WARP} | Public: {TARGET_PUBLIC}")
    log("=" * 60)

    # فاز ۱: WARP
    warp = hunt_warp()

    # فاز ۲: Public
    try:
        public = asyncio.run(hunt_public())
    except Exception as e:
        log(f"  ❌ public: {type(e).__name__}: {e}")
        public = []

    # نتیجه
    log("\n" + "=" * 60)
    log("🎯 نتیجه نهایی")
    log("=" * 60)
    log(f"🔌 WARP: {len(warp)} IP")
    log(f"🌐 Public: {len(public)} proxy")
    log(f"📊 مجموع: {len(warp) + len(public)}")


if __name__ == "__main__":
    main()
