"""
Proxy Farm — جمع‌آوری از منابع رایگان عمومی
- 7 منبع مختلف
- تست SOCKS5 + HTTP
- Self-Healing هر ۵ دقیقه
"""
import asyncio
import aiohttp
import json
import re
import time
import sys
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, '/root/tg_master_bot')

FARM_FILE = Path("/root/tg_master_bot/proxies/free_proxy_farm.json")
TEST_URL = "https://api.ipify.org"
TEST_TIMEOUT = 8

# ═══ منابع رایگان ═══
SOURCES = [
    # proxyscrape
    ("https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&protocol=socks5&timeout=5000&country=all&skip=0&proxy_format=ipport&format=text", "socks5", "text"),
    ("https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&protocol=http&timeout=5000&proxy_format=ipport&format=text", "http", "text"),
    # free-proxy-list.net
    ("https://free-proxy-list.net/", "http", "html"),
    ("https://www.socks-proxy.net/", "socks5", "html"),
    # github lists
    ("https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks5.txt", "socks5", "text"),
    ("https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt", "http", "text"),
    ("https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks5.txt", "socks5", "text"),
    ("https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt", "http", "text"),
    ("https://raw.githubusercontent.com/hookzof/socks5_list/master/proxy.txt", "socks5", "text"),
    # proxifly
    ("https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/socks5/data.txt", "socks5", "text"),
    ("https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/http/data.txt", "http", "text"),
]


async def fetch_source(session, url, ptype, kind):
    """جمع‌آوری از یه منبع"""
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as r:
            if r.status != 200:
                return []
            text = await r.text()
    except Exception:
        return []

    proxies = []
    if kind == "text":
        # الگو: ip:port
        for line in text.split("\n"):
            line = line.strip()
            if re.match(r'^\d+\.\d+\.\d+\.\d+:\d+$', line):
                proxies.append((ptype, line))
    elif kind == "html":
        # استخراج از HTML
        for match in re.finditer(r'(\d+\.\d+\.\d+\.\d+)[^\d]+(\d{2,5})', text):
            proxies.append((ptype, f"{match.group(1)}:{match.group(2)}"))

    return proxies


async def test_proxy(session, ptype, proxy_str, sem):
    """تست یه proxy"""
    async with sem:
        try:
            host, port = proxy_str.split(":")
            if ptype == "socks5":
                proxy_url = f"socks5://{host}:{port}"
            else:
                proxy_url = f"http://{host}:{port}"

            async with session.get(
                TEST_URL,
                proxy=proxy_url,
                timeout=aiohttp.ClientTimeout(total=TEST_TIMEOUT)
            ) as r:
                if r.status == 200:
                    ip = (await r.text()).strip()
                    if re.match(r'^\d+\.\d+\.\d+\.\d+$', ip):
                        return {
                            "type": ptype,
                            "proxy": proxy_str,
                            "exit_ip": ip,
                            "tested_at": datetime.now().isoformat(),
                        }
        except Exception:
            pass
        return None


async def collect_and_test():
    """جمع‌آوری و تست همه"""
    print("═" * 60)
    print("  🌐 Proxy Farm — جمع‌آوری از منابع رایگان")
    print("═" * 60)

    # ═══ ۱. جمع‌آوری ═══
    print(f"\n⏳ جمع‌آوری از {len(SOURCES)} منبع...")
    all_proxies = set()

    async with aiohttp.ClientSession() as session:
        tasks = [fetch_source(session, url, ptype, kind) for url, ptype, kind in SOURCES]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for i, result in enumerate(results):
            if isinstance(result, list):
                for ptype, p in result:
                    all_proxies.add((ptype, p))
                print(f"  {SOURCES[i][0][:60]}... → {len(result)}")

    print(f"\n📦 مجموع خام: {len(all_proxies)} proxy")

    # ═══ ۲. تست موازی ═══
    print(f"\n⏳ تست {len(all_proxies)} proxy (ممکنه ۲-۳ دقیقه طول بکشه)...")
    sem = asyncio.Semaphore(100)  # ۱۰۰ تا موازی

    async with aiohttp.ClientSession() as session:
        tasks = [test_proxy(session, ptype, p, sem) for ptype, p in all_proxies]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    healthy = [r for r in results if isinstance(r, dict)]

    # ═══ ۳. گروه‌بندی بر اساس IP خروجی ═══
    by_ip = {}
    for h in healthy:
        by_ip.setdefault(h["exit_ip"], []).append(h)

    print(f"\n✅ سالم: {len(healthy)} proxy")
    print(f"🌐 IP یکتا: {len(by_ip)}")

    # ═══ ۴. ذخیره ═══
    data = {
        "updated_at": datetime.now().isoformat(),
        "total_proxies": len(healthy),
        "unique_ips": len(by_ip),
        "proxies": healthy,
        "by_exit_ip": {ip: len(lst) for ip, lst in by_ip.items()},
    }
    FARM_FILE.parent.mkdir(parents=True, exist_ok=True)
    FARM_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    print(f"\n💾 ذخیره شد: {FARM_FILE}")

    # نمونه
    print(f"\n📋 نمونه ۱۰ proxy:")
    for h in healthy[:10]:
        print(f"  {h['type']}://{h['proxy']} → IP: {h['exit_ip']}")

    return len(by_ip)


if __name__ == "__main__":
    import nest_asyncio
    asyncio.run(collect_and_test())
