"""
توزیع اکانت‌ها روی همه IPها (WARP + Public)
"""
import json
import sys
from pathlib import Path
from collections import Counter

sys.path.insert(0, '/root/tg_master_bot')
from models import database as db

WARP_FILE = Path("/root/tg_master_bot/proxies/healthy_ports.json")
PUBLIC_FILE = Path("/root/tg_master_bot/proxies/public_proxies.json")
MAPPING_FILE = Path("/root/tg_master_bot/proxies/account_proxy.json")


def main():
    db.init_db()

    # ═══ جمع‌آوری همه proxyها ═══
    all_proxies = []  # list of {"type": "warp"/"public", "proxy_type": "socks5"/"http", "addr", "port"}

    # WARP
    if WARP_FILE.exists():
        d = json.loads(WARP_FILE.read_text())
        for ip, ports in d.get("ip_to_ports", {}).items():
            for p in ports:
                all_proxies.append({
                    "source": "warp",
                    "proxy_type": "socks5",
                    "addr": "127.0.0.1",
                    "port": int(p),
                    "ip": ip,
                })

    # Public
    if PUBLIC_FILE.exists():
        d = json.loads(PUBLIC_FILE.read_text())
        for p in d.get("proxies", []):
            try:
                host, port = p["proxy"].split(":")
                all_proxies.append({
                    "source": "public",
                    "proxy_type": p["type"],  # socks5 یا http
                    "addr": host,
                    "port": int(port),
                    "ip": p["exit_ip"],
                })
            except Exception:
                continue

    print(f"📦 WARP: {sum(1 for p in all_proxies if p['source']=='warp')}")
    print(f"📦 Public: {sum(1 for p in all_proxies if p['source']=='public')}")
    print(f"📦 کل: {len(all_proxies)}")

    if not all_proxies:
        print("❌ هیچ proxy نیست")
        return

    # ═══ اکانت‌ها ═══
    accounts = db.get_all_accounts()
    print(f"👥 اکانت: {len(accounts)}")

    # ═══ توزیع round-robin ═══
    mapping = {}  # phone → proxy dict

    for i, acc in enumerate(accounts):
        p = all_proxies[i % len(all_proxies)]
        mapping[acc["phone"]] = p

    # ═══ ذخیره ═══
    MAPPING_FILE.write_text(json.dumps(mapping, indent=2))

    # ═══ آمار ═══
    ip_count = Counter(p["ip"] for p in mapping.values())
    print(f"\n📊 توزیع {len(accounts)} اکانت روی {len(set(m['ip'] for m in mapping.values()))} IP یکتا")
    print(f"   (میانگین {len(accounts) // max(len(ip_count), 1)} اکانت per IP)")

    src_count = Counter(p["source"] for p in mapping.values())
    for s, n in src_count.items():
        print(f"   {s}: {n}")


if __name__ == "__main__":
    main()
