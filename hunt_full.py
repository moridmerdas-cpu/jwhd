"""
Hunt Full — 20 دقیقه search + collection
"""
import subprocess, time, shutil, re, random, json, socket, sys, asyncio, aiohttp
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

POOL_DIR = Path("/root/tg_master_bot/proxies/warp_pool")
STATE_FILE = Path("/root/tg_master_bot/proxies/healthy_ports.json")
PUBLIC_PROXY_FILE = Path("/root/tg_master_bot/proxies/public_proxies.json")
LOG_FILE = Path("/root/tg_master_bot/logs/hunt.log")

DURATION_MINUTES = 20

# ═══ 40 endpoint WARP ═══
ENDPOINTS = []
for base in ["162.159.192", "162.159.193", "188.114.96", "188.114.97", "188.114.98", "188.114.99"]:
    for i in range(1, 10):
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

# ═══ منابع پروکسی عمومی ═══
PROXY_SOURCES = [
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks5.txt",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks5.txt",
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
    "https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/socks5/data.txt",
    "https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/http/data.txt",
    "https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&protocol=socks5&timeout=3000&format=text&proxy_format=ipport",
    "https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&protocol=http&timeout=3000&format=text&proxy_format=ipport",
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


# ═══════════════════════════════════════════════════════════
#  بخش ۱: WARP IP Hunting
# ═══════════════════════════════════════════════════════════
def get_port(conf):
    try:
        for line in conf.read_text().splitlines():
            if "BindAddress" in line:
                return int(line.split(":")[-1].strip())
    except Exception:
        pass
    return None


def test_socks(port, timeout=10):
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


def kill_inst(d):
    try:
        pf = d / "wireproxy.pid"
        if pf.exists():
            subprocess.run(["kill", "-9", pf.read_text().strip()], capture_output=True)
    except Exception:
        pass
    subprocess.run(["pkill", "-9", "-f", str(d)], capture_output=True)


def warp_register(idx, port):
    """ثبت یه WARP"""
    d = POOL_DIR / f"warp_h_{idx}_{port}"
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True, exist_ok=True)
    ep = random.choice(ENDPOINTS)

    try:
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

        for _ in range(3):
            ip = test_socks(port, timeout=10)
            if ip:
                return {"port": port, "ip": ip, "ep": ep, "dir": str(d)}
            time.sleep(3)

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


def warp_hunt_batch(batch_size, start_port, collected_ips):
    """یه دسته hunt"""
    print(f"\n  🎯 Batch: {batch_size} parallel | ports {start_port}+")
    results = []
    with ThreadPoolExecutor(max_workers=batch_size) as ex:
        futures = {ex.submit(warp_register, i, start_port + i): i for i in range(batch_size)}
        for fut in as_completed(futures):
            try:
                res = fut.result()
                if res:
                    results.append(res)
            except Exception:
                pass

    by_ip = {}
    for r in results:
        by_ip.setdefault(r["ip"], []).append(r)

    # پاک کردن تکراری‌ها
    keep = {}
    for ip, items in by_ip.items():
        if ip in collected_ips:
            # قبلاً داشتیم، همه رو بکش
            for item in items:
                kill_inst(Path(item["dir"]))
                shutil.rmtree(item["dir"], ignore_errors=True)
            print(f"  🔁 {ip} تکراری")
            continue
        keep[ip] = items[0]
        # بقیه رو بکش
        for extra in items[1:]:
            kill_inst(Path(extra["dir"]))
            shutil.rmtree(extra["dir"], ignore_errors=True)
        print(f"  ✅ {ip} جدید → port {items[0]['port']}")

    return keep


# ═══════════════════════════════════════════════════════════
#  بخش ۲: Public Proxy Collection
# ═══════════════════════════════════════════════════════════
async def fetch_proxy_source(session, url):
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
            out.append(f"{m.group(1)}:{m.group(2)}")
    return out


async def test_public_proxy(session, proxy_str, sem):
    async with sem:
        host, port = proxy_str.split(":")
        for ptype in ["socks5", "http"]:
            try:
                proxy_url = f"{ptype}://{host}:{port}"
                async with session.get(
                    "https://api.ipify.org",
                    proxy=proxy_url,
                    timeout=aiohttp.ClientTimeout(total=6)) as r:
                    if r.status == 200:
                        ip = (await r.text()).strip()
                        if re.match(r'^\d+\.\d+\.\d+\.\d+$', ip):
                            return {"type": ptype, "proxy": proxy_str, "exit_ip": ip}
            except Exception:
                continue
        return None


async def collect_public_proxies():
    log("\n═══ جمع‌آوری پروکسی‌های عمومی ═══")
    async with aiohttp.ClientSession() as session:
        tasks = [fetch_proxy_source(session, url) for url in PROXY_SOURCES]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    all_proxies = set()
    for r in results:
        if isinstance(r, list):
            for p in r:
                all_proxies.add(p)

    log(f"📦 جمع‌آوری: {len(all_proxies)} پروکسی خام")

    if not all_proxies:
        return []

    # تست موازی
    to_test = list(all_proxies)[:2000]
    log(f"⏳ تست {len(to_test)} پروکسی (500 موازی)...")

    sem = asyncio.Semaphore(500)
    healthy = []

    async with aiohttp.ClientSession() as session:
        tasks = [test_public_proxy(session, p, sem) for p in to_test]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for r in results:
            if isinstance(r, dict):
                healthy.append(r)

    log(f"✅ سالم: {len(healthy)} پروکسی")
    if healthy:
        by_ip = {}
        for h in healthy:
            by_ip.setdefault(h["exit_ip"], 0)
            by_ip[h["exit_ip"]] += 1
        log(f"🌐 IP یکتا: {len(by_ip)}")

    # ذخیره
    PUBLIC_PROXY_FILE.write_text(json.dumps({
        "updated_at": datetime.now().isoformat(),
        "total": len(healthy),
        "proxies": healthy,
    }, indent=2))

    return healthy


# ═══════════════════════════════════════════════════════════
#  بخش ۳: Main — Hunt 20 دقیقه‌ای
# ═══════════════════════════════════════════════════════════
def main():
    log("═" * 60)
    log(f"🎯 Hunt Full — {DURATION_MINUTES} دقیقه")
    log("═" * 60)

    start_time = time.time()
    deadline = start_time + DURATION_MINUTES * 60

    # ═══ فاز ۱: WARP Hunting (۱۵ دقیقه) ═══
    log("\n═══ فاز ۱: WARP IP Hunting ═══")

    collected_ips = {}  # ip → {port, dir}

    # IPهای موجود رو نگه‌دار
    if STATE_FILE.exists():
        try:
            existing = json.loads(STATE_FILE.read_text()).get("ip_to_ports", {})
            for ip, ports in existing.items():
                for p in ports:
                    # چک کن هنوز زنده‌ست
                    test_ip = test_socks(p)
                    if test_ip == ip:
                        collected_ips[ip] = {"port": p, "dir": str(POOL_DIR / f"warp_{p}")}
                        log(f"  ✅ موجود: {ip} (port {p})")
        except Exception:
            pass

    log(f"📦 شروع با {len(collected_ips)} IP")

    batch_num = 0
    base_port = 42000
    target_ips = 6

    while time.time() < deadline and len(collected_ips) < target_ips:
        batch_num += 1
        log(f"\n🔄 Batch #{batch_num} | IP فعلی: {len(collected_ips)}/{target_ips}")

        new = warp_hunt_batch(
            batch_size=15,
            start_port=base_port + batch_num * 20,
            collected_ips=set(collected_ips.keys())
        )

        for ip, info in new.items():
            if ip not in collected_ips:
                collected_ips[ip] = info

        # ذخیره
        save_data = {}
        for ip, info in collected_ips.items():
            save_data[ip] = [info["port"]]

        p2i = {}
        for ip, ports in save_data.items():
            for p in ports:
                p2i[str(p)] = ip

        STATE_FILE.write_text(json.dumps({
            "updated_at": datetime.now().isoformat(),
            "unique_ips": len(save_data),
            "ip_to_ports": save_data,
            "port_to_ip": p2i,
        }, indent=2))

        log(f"📊 الان: {len(collected_ips)} IP")

        if len(collected_ips) >= target_ips:
            log(f"\n🎉 به هدف ({target_ips} IP) رسیدیم!")
            break

        # صبر کوتاه
        remaining = deadline - time.time()
        if remaining < 60:
            break
        wait = min(30, remaining - 10)
        log(f"⏳ صبر {wait:.0f}s قبل از batch بعدی...")
        time.sleep(wait)

    # ═══ فاز ۲: Public Proxy Collection (پس از Hunt) ═══
    if time.time() < deadline + 600:  # حتی اگه hunt تموم شد، پروکسی‌ها رو بگیر
        try:
            asyncio.run(collect_public_proxies())
        except Exception as e:
            log(f"❌ public proxies: {type(e).__name__}: {e}")

    # ═══ نتیجه نهایی ═══
    elapsed = (time.time() - start_time) / 60
    log("\n" + "═" * 60)
    log(f"🎯 نتیجه نهایی (بعد {elapsed:.1f} دقیقه)")
    log("═" * 60)

    log(f"\n🔌 WARP IP یکتا: {len(collected_ips)}")
    for ip, info in collected_ips.items():
        log(f"   {ip} → port {info['port']}")

    if PUBLIC_PROXY_FILE.exists():
        try:
            pp = json.loads(PUBLIC_PROXY_FILE.read_text())
            log(f"\n🌐 Public proxy: {pp['total']} عدد")
        except Exception:
            pass

    log("\n✅ Hunt تموم شد")


if __name__ == "__main__":
    main()
