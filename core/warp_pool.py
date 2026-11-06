import subprocess
import json
import time
import random
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import Config
from models import database as db

POOL_DIR = Config.BASE_DIR / "proxies" / "warp_pool"
POOL_DIR.mkdir(parents=True, exist_ok=True)

# Endpoint های متنوع برای گرفتن IP متفاوت از Cloudflare
ENDPOINTS = [
    # پورت‌های استاندارد WARP
    "188.114.96.1:2408", "188.114.97.1:2408", "188.114.98.1:2408",
    "188.114.99.1:2408", "162.159.192.1:2408", "162.159.193.1:2408",
    "162.159.195.1:2408", "162.159.204.1:2408",
    # پورت‌های جایگزین
    "188.114.96.1:500", "188.114.97.1:500", "188.114.98.1:500",
    "188.114.99.1:500", "162.159.192.1:500", "162.159.193.1:500",
    "162.159.195.1:500", "162.159.204.1:500",
    # پورت‌های 1002
    "188.114.99.224:1002", "188.114.98.224:1002", "188.114.96.224:1002",
    "188.114.97.224:1002", "188.114.100.224:1002", "188.114.101.224:1002",
    # گسترش
    "188.114.100.1:2408", "188.114.101.1:2408", "188.114.102.1:2408",
    "188.114.103.1:2408", "188.114.104.1:2408", "188.114.105.1:2408",
    "162.159.197.1:2408", "162.159.198.1:2408", "162.159.200.1:2408",
    "162.159.205.1:2408", "162.159.206.1:2408", "162.159.207.1:2408",
    # پورت‌های اضافی
    "188.114.96.1:1701", "188.114.97.1:1701", "188.114.98.1:1701",
    "188.114.99.1:1701", "162.159.192.1:1701", "162.159.193.1:1701",
    "188.114.96.1:890", "188.114.97.1:890", "188.114.98.1:890",
    "188.114.99.1:890", "162.159.192.1:890", "162.159.193.1:890",
    "188.114.96.1:4500", "188.114.97.1:4500", "188.114.98.1:4500",
    "188.114.99.1:4500", "162.159.192.1:4500",
    "188.114.96.1:1337", "188.114.97.1:1337", "188.114.98.1:1337",
    "188.114.99.1:1337", "162.159.192.1:1337",
    "188.114.96.1:7844", "188.114.97.1:7844", "188.114.98.1:7844",
    "188.114.99.1:7844", "162.159.192.1:7844",
    "188.114.96.1:8443", "188.114.97.1:8443", "188.114.98.1:8443",
    "188.114.99.1:8443", "162.159.192.1:8443",
    "188.114.96.1:2371", "188.114.97.1:2371", "188.114.98.1:2371",
    "188.114.99.1:2371", "162.159.192.1:2371",
    "188.114.96.1:5000", "188.114.97.1:5000", "188.114.98.1:5000",
    "188.114.99.1:5000", "162.159.192.1:5000",
]

APIS = [
    "https://yota-warp-self.vercel.app/api/generate?dns=1.1.1.1&mtu=1280&allowed_ips=0.0.0.0/0&keepalive=25",
]


def _fetch_config(api_url, max_attempts=3):
    for attempt in range(max_attempts):
        try:
            r = subprocess.run(
                ["curl", "-s", "--max-time", "30", api_url],
                capture_output=True, text=True, timeout=35
            )
            if r.returncode == 0 and r.stdout:
                data = json.loads(r.stdout)
                cfg = data.get("config", "")
                if cfg and "PrivateKey" in cfg:
                    return cfg
        except Exception as e:
            db.debug_log("warp_pool", "fetch", "WARN", f"تلاش {attempt+1}: {e}")
        time.sleep(5)
    return None


def _parse(raw):
    pk, pub, addr = "", "", ""
    for line in raw.split("\n"):
        line = line.strip()
        if line.startswith("PrivateKey"):
            pk = line.split("=", 1)[1].strip()
        elif line.startswith("PublicKey"):
            pub = line.split("=", 1)[1].strip()
        elif line.startswith("Address"):
            addr = line.split("=", 1)[1].strip().split(",")[0].strip()
    return pk, pub, addr


def _existing_keys():
    keys = set()
    for conf in POOL_DIR.glob("warp_*.conf"):
        try:
            for line in conf.read_text().split("\n"):
                if line.strip().startswith("PrivateKey"):
                    keys.add(line.split("=", 1)[1].strip())
                    break
        except Exception:
            pass
    return keys


def generate_one(slot, existing_keys, delay=8):
    port = 40000 + slot - 1
    conf_path = POOL_DIR / f"warp_{slot:03d}.conf"

    if conf_path.exists():
        content = conf_path.read_text()
        pk = ""
        for line in content.split("\n"):
            if line.strip().startswith("PrivateKey"):
                pk = line.split("=", 1)[1].strip()
                break
        if len(pk) >= 43:
            existing_keys.add(pk)
            return True
        conf_path.unlink()

    endpoint = random.choice(ENDPOINTS)
    raw = _fetch_config(APIS[0])
    if not raw:
        db.debug_log("warp_pool", "generate", "FAIL", f"slot {slot}: API fail")
        return False

    pk, pub, addr = _parse(raw)
    if not pk or not pub or len(pk) < 43:
        db.debug_log("warp_pool", "generate", "FAIL", f"slot {slot}: کلید ناقص")
        return False

    if pk in existing_keys:
        db.debug_log("warp_pool", "generate", "DUP", f"slot {slot}: تکراری")
        return False

    existing_keys.add(pk)

    content = f"""[Interface]
PrivateKey = {pk}
Address = {addr}
DNS = 1.1.1.1

[Peer]
PublicKey = {pub}
Endpoint = {endpoint}
AllowedIPs = 0.0.0.0/0
PersistentKeepalive = 25

[Socks5]
BindAddress = 127.0.0.1:{port}
"""
    conf_path.write_text(content)
    db.debug_log("warp_pool", "generate", "OK", f"slot {slot} → {port} | {endpoint}")
    time.sleep(delay)
    return True


def generate_all(target=75, delay=8):
    existing = _existing_keys()
    db.debug_log("warp_pool", "generate_all", "START", f"هدف: {target}")
    ok = 0
    for slot in range(1, target + 1):
        if generate_one(slot, existing, delay):
            ok += 1
    final = len(list(POOL_DIR.glob("warp_*.conf")))
    db.debug_log("warp_pool", "generate_all", "DONE", f"{ok} ساخته | مجموع {final}/{target}")
    return final


def get_all_configs():
    return sorted(POOL_DIR.glob("warp_*.conf"))


def get_port_from_conf(conf_path):
    try:
        for line in conf_path.read_text().split("\n"):
            if line.strip().startswith("BindAddress"):
                return int(line.split(":")[-1].strip())
    except Exception:
        pass
    return 0


def remove_config(conf_path):
    try:
        conf_path.unlink()
        db.debug_log("warp_pool", "remove", "OK", conf_path.name)
    except Exception:
        pass


def find_free_slot():
    for slot in range(1, 151):
        if not (POOL_DIR / f"warp_{slot:03d}.conf").exists():
            return slot
    return 0


if __name__ == "__main__":
    db.init_db()
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 75
    generate_all(count, delay=8)
