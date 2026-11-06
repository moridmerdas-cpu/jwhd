"""Public Proxy Hunt — فقط پروکسی‌های عمومی"""
import asyncio, aiohttp, re, json, time
from pathlib import Path
from datetime import datetime

PUBLIC_STATE = Path("/root/tg_master_bot/proxies/public_proxies.json")
LOG_FILE = Path("/root/tg_master_bot/logs/hunt_public.log")

TARGET = 100

SOURCES = [
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
    ("https://raw.githubusercontent.com/mmpx12/proxy-list/master/socks5.txt", "socks5"),
    ("https://raw.githubusercontent.com/mmpx12/proxy-list/master/http.txt", "http"),
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


async def fetch(session, url, ptype):
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


async def test_one(session, ptype, proxy_str, sem, results, counter, total):
    async with sem:
        try:
            url = f"{ptype}://{proxy_str}"
            async with session.get(
                "https://api.ipify.org",
                proxy=url,
                timeout=aiohttp.ClientTimeout(total=6)) as r:
                if r.status == 200:
                    ip = (await r.text()).strip()
                    if re.match(r'^\d+\.\d+\.\d+\.\d+$', ip):
                        results.append({"type": ptype, "proxy": proxy_str, "exit_ip": ip})
        except Exception:
            pass
        finally:
            counter[0] += 1


async def main():
    log("═" * 60)
    log("🌐 Public Hunt")
    log("═" * 60)

    # جمع‌آوری
    log("📥 جمع‌آوری از منابع...")
    all_proxies = set()

    async with aiohttp.ClientSession() as session:
        tasks = [fetch(session, url, ptype) for url, ptype in SOURCES]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    for r in results:
        if isinstance(r, list):
            for item in r:
                all_proxies.add(item)

    log(f"📦 جمع‌آوری: {len(all_proxies)} خام")

    if not all_proxies:
        log("❌ هیچ proxy خامی نیست")
        return

    # محدود به 5000
    to_test = list(all_proxies)[:5000]
    log(f"⏳ تست {len(to_test)} با 500 parallel...")

    sem = asyncio.Semaphore(500)
    results = []
    counter = [0]
    total = len(to_test)

    async with aiohttp.ClientSession() as session:
        # ═══ ساخت Task (نه coroutine) ═══
        tasks = []
        for pt, p in to_test:
            t = asyncio.create_task(test_one(session, pt, p, sem, results, counter, total))
            tasks.append(t)

        async def progress():
            while counter[0] < total:
                await asyncio.sleep(10)
                log(f"  ... {counter[0]}/{total} | سالم: {len(results)}")

        prog = asyncio.create_task(progress())
        await asyncio.gather(*tasks, return_exceptions=True)
        prog.cancel()

    # گروه‌بندی بر اساس IP یگانه
    by_ip = {}
    for r in results:
        by_ip.setdefault(r["exit_ip"], []).append(r)

    log(f"✅ سالم: {len(results)} | IP یگانه: {len(by_ip)}")

    # فقط یه proxy از هر IP
    unique = [items[0] for items in by_ip.values()]

    PUBLIC_STATE.write_text(json.dumps({
        "updated_at": datetime.now().isoformat(),
        "total": len(unique),
        "proxies": unique,
    }, indent=2))

    log(f"💾 ذخیره: {len(unique)} proxy یگانه در {PUBLIC_STATE}")

    # نمونه
    log("\n📋 نمونه ۱۰ proxy:")
    for u in unique[:10]:
        log(f"  {u['type']}://{u['proxy']} → {u['exit_ip']}")


if __name__ == "__main__":
    asyncio.run(main())
