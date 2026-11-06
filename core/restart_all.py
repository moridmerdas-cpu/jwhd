"""
راه‌اندازی مجدد سریع همه wireproxyها
"""
import subprocess
import time
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, '/root/tg_master_bot')
from config import Config

POOL_DIR = Config.PROXY_DIR / "warp_pool"


async def test_port(port):
    try:
        proc = await asyncio.create_subprocess_exec(
            "curl", "-s", "--max-time", "4",
            "-x", f"socks5h://127.0.0.1:{port}",
            "https://api.ipify.org",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=6)
        return port, stdout.decode().strip()
    except Exception:
        return port, ""


async def main():
    # ۱. کشتن همه
    print("🛑 کشتن همه wireproxy...")
    subprocess.run(["/usr/bin/pkill", "-9", "-f", "wireproxy"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(3)

    # ۲. راه‌اندازی مجدد همه
    configs = sorted(POOL_DIR.glob("warp_*.conf"))
    print(f"🚀 راه‌اندازی مجدد {len(configs)} کانفیگ...")
    started = 0
    for conf in configs:
        try:
            # پورت رو از کانفیگ بخون
            port = 0
            for line in conf.read_text().split("\n"):
                if line.strip().startswith("BindAddress"):
                    port = int(line.split(":")[-1].strip())
                    break
            if port == 0:
                continue

            log = POOL_DIR / f"warp_{port}.log"
            subprocess.Popen(
                ["wireproxy", "--config", str(conf)],
                stdout=open(log, "a"),
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            started += 1
            time.sleep(0.05)
        except Exception as e:
            print(f"  ❌ {conf.name}: {e}")

    print(f"✅ {started} پروسه شروع شد")
    print("⏳ صبر 15 ثانیه برای handshake...")
    await asyncio.sleep(15)

    # ۳. تست همه
    print("🧪 تست همه پورت‌ها...")
    sem = asyncio.Semaphore(20)
    async def test(port):
        async with sem:
            return await test_port(port)

    ports = []
    for conf in configs:
        for line in conf.read_text().split("\n"):
            if line.strip().startswith("BindAddress"):
                try:
                    ports.append(int(line.split(":")[-1].strip()))
                except Exception:
                    pass
                break

    results = await asyncio.gather(*[test(p) for p in ports])

    alive = sum(1 for _, ip in results if ip)
    print(f"\n📊 {alive}/{len(ports)} پورت سالم")


if __name__ == "__main__":
    asyncio.run(main())
