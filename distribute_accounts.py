"""
توزیع ۷۸ اکانت روی IPهای سالم
هر IP تعداد مساوی اکانت می‌گیره
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, '/root/tg_master_bot')
from models import database as db

STATE_FILE = Path("/root/tg_master_bot/proxies/healthy_ports.json")
MAPPING_FILE = Path("/root/tg_master_bot/proxies/account_proxy.json")


def main():
    db.init_db()

    if not STATE_FILE.exists():
        print("❌ healthy_ports.json نیست")
        return

    state = json.loads(STATE_FILE.read_text())
    ip_to_ports = state.get("ip_to_ports", {})
    if not ip_to_ports:
        print("❌ هیچ IP سالمی نیست")
        return

    # لیست پورت‌ها (یه پورت از هر IP)
    ports = []
    for ip, port_list in ip_to_ports.items():
        if port_list:
            ports.append(port_list[0])
    ports.sort()

    print(f"🌐 IP یکتا: {len(ip_to_ports)}")
    print(f"🔌 پورت‌ها: {ports}")
    print()

    # توزیع round-robin
    accounts = db.get_all_accounts()
    if not accounts:
        print("❌ اکانتی نیست")
        return

    n_ports = len(ports)
    mapping = {}

    for i, acc in enumerate(accounts):
        port = ports[i % n_ports]
        mapping[acc["phone"]] = port

    MAPPING_FILE.write_text(json.dumps(mapping, indent=2))

    # آمار
    from collections import Counter
    dist = Counter(mapping.values())
    print(f"📊 توزیع {len(accounts)} اکانت روی {n_ports} IP:")
    for port in sorted(dist.keys()):
        ip = state["port_to_ip"].get(str(port), "?")
        print(f"  port {port} ({ip}): {dist[port]} اکانت")

    print(f"\n✅ ذخیره: {MAPPING_FILE}")


if __name__ == "__main__":
    main()
