"""
Proxy Farm v3 — اصلاح‌شده و سریع
"""
import asyncio
import aiohttp
import json
import re
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, '/root/tg_master_bot')

FARM_FILE = Path("/root/tg_master_bot/proxies/free_proxy_farm.json")
TEST_URL = "https://api.ipify.org"
TIMEOUT = 4
CONCURRENCY = 500
MAX_TEST = 3000

SOURCES = [
    ("https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&protocol=socks5&timeout=3000&format=text&proxy_format=ipport", "socks5"),
    ("https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&protocol=http&timeout=3000&format=text&proxy_format=ipport", "http"),
    ("https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks5.txt", "socks5"),
    ("https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt", "http"),
    ("https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/socks5/data.txt", "socks5"),
    ("https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/http/data.txt", "http"),
]


async def fetch(session, url, ptype):
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as r:
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


async def test_one(session, ptype, proxy_str, sem, results, counter):
    async with sem:
        try:
            host, port = proxy_str.split(":")
            url = f"socks5://{host}:{port}" if ptype == "socks5" else f"http://{host}:{port}"
            async with session.get(
                TEST_URL,
                proxy=url,
                timeout=aiohttp.ClientTimeout(total=TIMEOUT)
            ) as r:
                if r.status == 200:
                    ip = (await r.text()).strip()
                    if re.match(r'^\d+\.\d+\.\d+\.\d+$', ip):
                        results.append({
                            "type": ptype,
                            "proxy": proxy_str,
                            "exit_ip": ip,
                            "tested_at": datetime.now().isoformat(),
                        })
        except Exception:
            pass
        finally:
            counter[0] += 1


async def main():
    print("═" * 60)
    print("  🌐 Proxy Farm v3")
    print("═" * 60)

    # ═══ جمع‌آوری ═══
    print(f"\n⏳ جمع‌آوری از {len(SOURCES)} منبع...")
    all_proxies = set()
    async with aiohttp.ClientSession() as session:
        for url, ptype in SOURCES:
            res = await fetch(session, url, ptype)
            for _, p in res:
                all_proxies.add((ptype, p))
            print(f"  {url.split('/')[2]:35s} → {len(res)}")

    print(f"\n📦 مجموع خام (بعد از dedup): {len(all_proxies)}")

    to_test = list(all_proxies)[:MAX_TEST]
    print(f"🎯 تست روی {len(to_test)} proxy | موازی: {CONCURRENCY} | timeout: {TIMEOUT}s")

    # ═══ تست موازی ═══
    print(f"\n⏳ شروع تست...")
    sem = asyncio.Semaphore(CONCURRENCY)
    results = []
    counter = [0]
    total = len(to_test)

    async def progress_loop():
        while counter[0] < total:
            await asyncio.sleep(5)
            print(f"  ... {counter[0]}/{total} | سالم: {len(results)}")

    async with aiohttp.ClientSession() as session:
        tasks = [
            asyncio.create_task(test_one(session, pt, p, sem, results, counter))
            for pt, p in to_test
        ]
        prog = asyncio.create_task(progress_loop())
        await asyncio.gather(*tasks, return_exceptions=True)
        prog.cancel()

    # ═══ گروه‌بندی ═══
    by_ip = {}
    for r in results:
        by_ip.setdefault(r["exit_ip"], []).append(r)

    print(f"\n✅ سالم: {len(results)} proxy")
    print(f"🌐 IP یکتا: {len(by_ip)}")

    # ═══ ذخیره ═══
    data = {
        "updated_at": datetime.now().isoformat(),
        "total_proxies": len(results),
        "unique_ips": len(by_ip),
        "proxies": results,
        "by_exit_ip": {ip: len(lst) for ip, lst in by_ip.items()},
    }
    FARM_FILE.parent.mkdir(parents=True, exist_ok=True)
    FARM_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    print(f"\n💾 ذخیره: {FARM_FILE}")

    print(f"\n📋 نمونه ۱۰ proxy سالم:")
    for r in results[:10]:
        print(f"  {r['type']:6s}://{r['proxy']:22s} → {r['exit_ip']}")

    return len(by_ip)


if __name__ == "__main__":
    n = asyncio.run(main())
    print(f"\n🎯 نتیجه نهایی: {n} IP یکتا")
