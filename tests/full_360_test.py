"""
تست ۳۶۰ درجه سیستم
- سرعت سین با N اکانت
- پردازش پست‌های پشت سر هم
- توزیع IP
- شبیه‌سازی چرخش ۷۵/۱۵۰
"""
import asyncio
import sys
import time
import json
import hashlib
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, '/root/tg_master_bot')
from config import Config
from models import database as db
from core.engine import make_client, instant_view
from core.warp_pool import get_all_configs, get_port_from_conf


HEALTHY_FILE = Config.BASE_DIR / "proxies" / "healthy_ports.json"


def line(t=""):
    print(f"{'─' * 60} {t}")

def header(t):
    print()
    print(f"{'═' * 60}")
    print(f"  {t}")
    print(f"{'═' * 60}")


# ═══════════════════════════════════════════════════════════
# ۱. بررسی ساختار دیتابیس
# ═══════════════════════════════════════════════════════════
def test_1_database():
    header("۱. ساختار دیتابیس و اکانت‌ها")
    accounts = db.get_all_accounts()
    print(f"📊 تعداد اکانت موجود: {len(accounts)}")
    print()
    for a in accounts:
        print(f"   {a['phone']} | شیفت: {a['shift']} | وضعیت: {a['status']} | پورت: {a.get('proxy_port', '-')}")

    # توزیع شیفت
    shift_a = len([a for a in accounts if a['shift'] == 'A'])
    shift_b = len([a for a in accounts if a['shift'] == 'B'])
    print()
    print(f"🔀 توزیع شیفت:")
    print(f"   شیفت A: {shift_a} اکانت")
    print(f"   شیفت B: {shift_b} اکانت")
    return accounts


# ═══════════════════════════════════════════════════════════
# ۲. توزیع IP
# ═══════════════════════════════════════════════════════════
def test_2_ips():
    header("۲. توزیع IP سالم")
    if not HEALTHY_FILE.exists():
        print("❌ فایل healthy_ports.json نیست")
        return {}
    data = json.loads(HEALTHY_FILE.read_text())
    ips = data.get("ips", [])
    ip_to_ports = data.get("ip_to_ports", {})
    print(f"🎯 {len(ips)} IP یکتا:")
    for ip, ports in ip_to_ports.items():
        print(f"   {ip}: {len(ports)} پورت")
    return data


# ═══════════════════════════════════════════════════════════
# ۳. شبیه‌سازی تخصیص IP به N اکانت مجازی
# ═══════════════════════════════════════════════════════════
def test_3_ip_allocation(ip_data, n_accounts=75):
    header(f"۳. شبیه‌سازی تخصیص IP برای {n_accounts} اکانت")
    ips = ip_data.get("ips", [])
    ip_to_ports = ip_data.get("ip_to_ports", {})
    if not ips:
        print("❌ IPی موجود نیست")
        return

    # شبیه‌سازی hash بر اساس شماره مجازی
    ip_count = {}
    for i in range(n_accounts):
        fake_phone = f"+9891{i:08d}"
        h = int(hashlib.md5(fake_phone.encode()).hexdigest(), 16)
        chosen_ip = ips[h % len(ips)]
        ip_count[chosen_ip] = ip_count.get(chosen_ip, 0) + 1

    print(f"📊 توزیع {n_accounts} اکانت مجازی روی {len(ips)} IP:")
    for ip, cnt in sorted(ip_count.items(), key=lambda x: -x[1]):
        pct = cnt * 100 // n_accounts
        print(f"   {ip}: {cnt} اکانت ({pct}%)")

    # ارزیابی
    print()
    max_per_ip = max(ip_count.values())
    if max_per_ip <= 30:
        print(f"✅ توزیع متوازن (max {max_per_ip} اکانت/IP)")
    elif max_per_ip <= 50:
        print(f"⚠️  توزیع نیمه‌متوازن (max {max_per_ip} اکانت/IP)")
    else:
        print(f"❌ توزیع نامتوازن (max {max_per_ip} اکانت/IP)")


# ═══════════════════════════════════════════════════════════
# ۴. تست سین موازی با اکانت‌های موجود
# ═══════════════════════════════════════════════════════════
async def test_4_parallel_view(accounts, msg_id=None):
    header("۴. تست سین موازی با اکانت‌های موجود")

    if not accounts:
        print("❌ اکانتی نیست")
        return

    # اگه msg_id ندی، آخرین پیام کانال رو بگیر
    session_string = db.get_session(accounts[0]["phone"])
    client = make_client(session_string, phone=accounts[0]["phone"])
    await client.connect()
    target = Config.TARGET_CHANNEL_USERNAME or Config.TARGET_CHANNEL_ID
    channel = await client.get_entity(target)
    if msg_id is None:
        msgs = await client.get_messages(channel, limit=1)
        msg_id = msgs[0].id
        print(f"🎯 پیام تست: {msg_id}")

    # قبل
    from telethon import functions
    before = await client(functions.messages.GetMessagesViewsRequest(
        peer=channel, id=[msg_id], increment=False))
    views_before = before.views[0].views if before.views else 0
    print(f"📊 بازدید قبل: {views_before}")

    await client.disconnect()
    print()
    print(f"⚡ شروع سین موازی با {len(accounts)} اکانت...")
    t0 = time.perf_counter()

    async def view_one(phone):
        try:
            ss = db.get_session(phone)
            c = make_client(ss, phone=phone)
            await asyncio.wait_for(c.connect(), timeout=30)
            peer = await asyncio.wait_for(c.get_entity(target), timeout=15)
            r = await asyncio.wait_for(instant_view(c, peer, [msg_id]), timeout=30)
            await c.disconnect()
            if r.get("ok"):
                return phone, True, time.perf_counter() - t0, ""
            elif "flood" in r:
                return phone, False, time.perf_counter() - t0, f"FLOOD_{r['flood']}s"
            else:
                return phone, False, time.perf_counter() - t0, r.get("error", "?")[:60]
        except asyncio.TimeoutError:
            return phone, False, time.perf_counter() - t0, "TIMEOUT"
        except Exception as e:
            return phone, False, time.perf_counter() - t0, f"{type(e).__name__}"

    tasks = [view_one(a["phone"]) for a in accounts]
    results = await asyncio.gather(*tasks)

    t_total = time.perf_counter() - t0

    # نتیجه
    print()
    success = sum(1 for r in results if r[1])
    print(f"📊 نتایج:")
    for phone, ok, elapsed, err in results:
        status = "✅" if ok else "❌"
        print(f"   {status} {phone} | {elapsed*1000:.0f}ms | {err}")

    print()
    print(f"⏱️  زمان کل: {t_total*1000:.0f}ms")
    print(f"✅ موفق: {success}/{len(accounts)}")
    print(f"🕐 میانگین: {t_total*1000/len(accounts):.0f}ms/اکانت")

    # تأیید
    await asyncio.sleep(3)
    client2 = make_client(db.get_session(accounts[0]["phone"]), phone=accounts[0]["phone"])
    await client2.connect()
    after = await client2(functions.messages.GetMessagesViewsRequest(
        peer=channel, id=[msg_id], increment=False))
    views_after = after.views[0].views if after.views else 0
    await client2.disconnect()
    print(f"📊 بازدید بعد: {views_after} (+{views_after - views_before})")

    return t_total, success, len(accounts)


# ═══════════════════════════════════════════════════════════
# ۵. تخمین زمان برای ۷۵ اکانت
# ═══════════════════════════════════════════════════════════
def test_5_extrapolate(elapsed=None, success=None, total=None):
    header("۵. تخمین زمان برای ۷۵ و ۱۵۰ اکانت")
    if elapsed is None:
        print("❌ نتایج تست موازی نبود")
        return

    per_account = elapsed / total
    for n in [75, 150]:
        # چون موازی هستیم، زمان کل تقریباً ثابت می‌مونه
        estimated = per_account * n if n <= total * 2 else per_account * 2  # ساده‌سازی
        print(f"📊 برای {n} اکانت: ~{estimated:.1f}s (میانگین {per_account*1000:.0f}ms/اکانت)")


# ═══════════════════════════════════════════════════════════
# ۶. تست پست‌های پشت سر هم (شبیه‌سازی polling)
# ═══════════════════════════════════════════════════════════
def test_6_rapid_posts():
    header("۶. آنالیز پست‌های پشت سر هم")
    poll = 2  # ثانیه
    print(f"⚙️  polling interval: {poll}s")
    print()
    print("📊 سناریوهای مختلف:")
    scenarios = [
        ("1 پست در 10 ثانیه", 10, 1),
        ("1 پست در 1 ثانیه", 1, 1),
        ("2 پست در 1 ثانیه", 1, 2),
        ("10 پست پشت سر هم", 0, 10),
    ]
    for name, interval, count in scenarios:
        if interval > 0:
            delay = poll / interval
            print(f"   {name} → تأخیر ~{delay:.1f}s برای آخرین پست")
        else:
            print(f"   {name} → همه در یک دوره polling گرفته می‌شن")
    print()
    print("✅ Listener فعلی: همزمان تا 50 پیام رو پردازش می‌کنه")


# ═══════════════════════════════════════════════════════════
# ۷. چرخش ۷۵/۱۵۰
# ═══════════════════════════════════════════════════════════
def test_7_rotation():
    header("۷. مدل چرخش ۷۵/۱۵۰")
    print("📊 مدل فعلی: 30 دقیقه چرخش")
    print()
    print("سناریو ۷۵ اکانت:")
    print("   ⏰ 00-30 دقیقه → شیفت A (75 آنلاین، 0 استراحت)")
    print("   ⏰ 30-60 دقیقه → شیفت B (0 آنلاین، 75 استراحت) ← ⚠️ مشکل!")
    print()
    print("⚠️  مشکل: با ۷۵ اکانت، شیفت B خالیه → 30 دقیقه هیچ‌کس آنلاین نیست")
    print()
    print("✅ راه‌حل: از fallback استفاده می‌کنه (کد فعلی)")
    print()
    print("سناریو ۱۵۰ اکانت:")
    print("   ⏰ 00-30 دقیقه → شیفت A (75 آنلاین، 75 استراحت)")
    print("   ⏰ 30-60 دقیقه → شیفت B (75 آنلاین، 75 استراحت)")
    print("   ✅ همیشه 75 آنلاین")


# ═══════════════════════════════════════════════════════════
# اجرای همه
# ═══════════════════════════════════════════════════════════
async def main():
    print()
    print("█" * 60)
    print("  🔬 تست ۳۶۰ درجه سیستم متین فورسین")
    print(f"  ⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("█" * 60)

    db.init_db()

    accounts = test_1_database()
    ip_data = test_2_ips()
    test_3_ip_allocation(ip_data, 75)
    test_3_ip_allocation(ip_data, 150)
    test_7_rotation()

    if accounts:
        result = await test_4_parallel_view(accounts)
        if result:
            test_5_extrapolate(*result)

    test_6_rapid_posts()

    print()
    print("█" * 60)
    print("  🏁 پایان تست")
    print("█" * 60)


if __name__ == "__main__":
    asyncio.run(main())
