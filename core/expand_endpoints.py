"""
تست endpointهای جدید برای پیدا کردن IPهای متفاوت
"""
import asyncio
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import Config

# endpointهای جدید که تست نشده
NEW_ENDPOINTS = [
    "188.114.100.1:500",
    "188.114.101.1:500",
    "188.114.102.1:500",
    "188.114.103.1:500",
    "188.114.104.1:500",
    "188.114.105.1:500",
    "188.114.106.1:500",
    "188.114.107.1:500",
    "162.159.205.1:500",
    "162.159.206.1:500",
    "162.159.207.1:500",
    "162.159.208.1:500",
    "162.159.209.1:500",
    "162.159.210.1:500",
    "188.114.96.1:1701",
    "188.114.97.1:1701",
    "188.114.98.1:1701",
    "188.114.99.1:1701",
]


async def test_endpoint(ep):
    """تست یه endpoint با یه کانفیگ موقت"""
    import tempfile
    import subprocess

    # از کانفیگ موجود کپی بگیر و endpoint رو عوض کن
    src = None
    for conf in (Config.PROXY_DIR / "warp_pool").glob("warp_*.conf"):
        src = conf
        break
    if not src:
        return None

    content = src.read_text()
    lines = content.split("\n")
    new_lines = []
    for line in content.split("\n"):
        if line.startswith("Endpoint"):
            new_lines.append(f"Endpoint = {ep}")
        elif line.startswith("BindAddress"):
            new_lines.append(f"BindAddress = 127.0.0.1:45000")
        else:
            new_lines.append(line)

    tmp = Path("/tmp/test_warp.conf")
    tmp.write_text("\n".join(new_lines))

    proc = subprocess.Popen(
        ["wireproxy", "--config", str(tmp)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    await asyncio.sleep(8)

    try:
        proc2 = await asyncio.create_subprocess_exec(
            "curl", "-s", "--max-time", "5",
            "-x", "socks5h://127.0.0.1:45000",
            "https://api.ipify.org",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc2.communicate(), timeout=8)
        ip = stdout.decode().strip()
    except Exception:
        ip = ""

    proc.terminate()
    proc.wait(timeout=3)
    return ep, ip


async def main():
    print("🔍 تست endpointهای جدید...")
    for ep in NEW_ENDPOINTS:
        ep_name, ip = await test_endpoint(ep)
        if ip:
            print(f"   ✅ {ep} → {ip}")
        else:
            print(f"   ❌ {ep} → timeout")
        await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(main())
