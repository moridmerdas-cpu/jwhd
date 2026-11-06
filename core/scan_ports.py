"""
اسکن پورت‌های سالم و ذخیره در فایل
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import Config
from core.warp_pool import get_all_configs, get_port_from_conf

OUTPUT = Config.BASE_DIR / "proxies" / "healthy_ports.json"


async def check_port(port, sem):
    async with sem:
        try:
            proc = await asyncio.create_subprocess_exec(
                "curl", "-s", "--max-time", "6",
                "-x", f"socks5h://127.0.0.1:{port}",
                "https://api.ipify.org",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=9)
            ip = stdout.decode().strip()
            return port, ip
        except Exception:
            return port, ""


async def main():
    configs = get_all_configs()
    print(f"📁 {len(configs)} کانفیگ یافت شد")
    print("🔍 اسکن همه پورت‌ها (موازی)...")

    sem = asyncio.Semaphore(20)
    tasks = []
    for conf in configs:
        port = get_port_from_conf(conf)
        if port > 0:
            tasks.append(check_port(port, sem))

    results = await asyncio.gather(*tasks)

    # گروه‌بندی بر اساس IP
    ip_to_ports = {}
    for port, ip in results:
        if ip:
            ip_to_ports.setdefault(ip, []).append(port)

    print()
    print("═" * 50)
    print(f"✅ {sum(len(v) for v in ip_to_ports.values())} پورت سالم")
    print(f"🎯 {len(ip_to_ports)} IP یکتا:")
    for ip, ports in sorted(ip_to_ports.items()):
        print(f"   {ip}: {len(ports)} پورت")
    print("═" * 50)

    # ذخیره در فایل
    data = {
        "ips": list(ip_to_ports.keys()),
        "ip_to_ports": ip_to_ports,
        "port_to_ip": {str(p): ip for ip, ports in ip_to_ports.items() for p in ports},
    }
    OUTPUT.write_text(json.dumps(data, indent=2))
    print(f"\n✅ ذخیره شد: {OUTPUT}")


if __name__ == "__main__":
    asyncio.run(main())
