"""
تست: ۱۰ اکانت با ۱۰ پروکسی متفاوت → view روی یه پیام
مقایسه با ۱۰ اکانت بدون پروکسی
"""
import asyncio
import json
import sys
from pathlib import Path
sys.path.insert(0, '/root/tg_master_bot')

from config import Config
from models import database as db
from core.engine import make_client
from telethon import functions


async def view_with_proxy(phone, proxy, target, msg_id):
    """view با یه پروکسی مشخص"""
    ss = db.get_session(phone)
    if not ss:
        return phone, None, "NO_SESSION"

    c = make_client(ss)
    # اعمال پروکسی
    if proxy["type"] == "socks5":
        c.set_proxy({
            "proxy_type": "socks5",
            "addr": proxy["proxy"].split(":")[0],
            "port": int(proxy["proxy"].split(":")[1]),
            "rdns": True,
        })
    else:  # http
        c.set_proxy({
            "proxy_type": "http",
            "addr": proxy["proxy"].split(":")[0],
            "port": int(proxy["proxy"].split(":")[1]),
        })

    try:
        await asyncio.wait_for(c.connect(), timeout=20)
        if not await c.is_user_authorized():
            await c.disconnect()
            return phone, proxy.get("exit_ip"), "NOT_AUTH"

        # view
        r = await asyncio.wait_for(
            c(functions.messages.GetMessagesViewsRequest(
                peer=target, id=[msg_id], increment=True)),
            timeout=15)
        views = r.views[0].views if r.views else "?"
        await c.disconnect()
        return phone, proxy.get("exit_ip"), f"OK views={views}"
    except Exception as e:
        try:
            await c.disconnect()
        except Exception:
            pass
        return phone, proxy.get("exit_ip"), f"{type(e).__name__}: {str(e)[:50]}"


async def view_no_proxy(phone, target, msg_id):
    """view بدون پروکسی (IP سرور)"""
    ss = db.get_session(phone)
    if not ss:
        return phone, "NO_SESSION"
    c = make_client(ss)
    try:
        await asyncio.wait_for(c.connect(), timeout=20)
        if not await c.is_user_authorized():
            await c.disconnect()
            return phone, "NOT_AUTH"
        r = await asyncio.wait_for(
            c(functions.messages.GetMessagesViewsRequest(
                peer=target, id=[msg_id], increment=True)),
            timeout=15)
        views = r.views[0].views if r.views else "?"
        await c.disconnect()
        return phone, f"OK views={views}"
    except Exception as e:
        try:
            await c.disconnect()
        except Exception:
            pass
        return phone, f"{type(e).__name__}"


async def main():
    db.init_db()

    print("═" * 70)
    print("  🔬 تست: مقایسه ۱۰ اکانت با پروکسی vs بدون پروکسی")
    print("═" * 70)

    # بارگذاری farm
    farm_file = Path("/root/tg_master_bot/proxies/free_proxy_farm.json")
    if not farm_file.exists():
        print("❌ farm file نیست")
        return

    farm = json.loads(farm_file.read_text())
    proxies = farm["proxies"]
    print(f"\n📦 پروکسی موجود: {len(proxies)}")
    print(f"🌐 IP یکتا: {farm['unique_ips']}")

    accounts = db.get_all_accounts()
    print(f"👥 اکانت: {len(accounts)}")

    target = Config.TARGET_CHANNEL_USERNAME or Config.TARGET_CHANNEL_ID

    # دریافت آخرین پیام
    admin_ss = db.get_session(accounts[0]["phone"])
    c = make_client(admin_ss)
    await c.connect()
    ch = await c.get_entity(target)
    msgs = await c.get_messages(ch, limit=1)
    msg_id = msgs[0].id
    r = await c(functions.messages.GetMessagesViewsRequest(
        peer=ch, id=[msg_id], increment=False))
    before = r.views[0].views if r.views else "?"
    print(f"\n📩 پیام: ID={msg_id} | views قبل: {before}")
    await c.disconnect()

    # ═══ گروه ۱: ۱۰ اکانت با پروکسی ═══
    print(f"\n{'━'*70}")
    print(f"  🅰️ گروه ۱: ۱۰ اکانت با پروکسی (۱۰ IP متفاوت)")
    print(f"{'━'*70}")

    sample_with = accounts[:10]
    # تخصیص پروکسی متفاوت به هر کدوم
    tasks = []
    for i, acc in enumerate(sample_with):
        if i < len(proxies):
            proxy = proxies[i]
        else:
            proxy = proxies[i % len(proxies)]
        tasks.append(view_with_proxy(acc["phone"], proxy, target, msg_id))

    results = await asyncio.gather(*tasks)
    for phone, ip, status in results:
        emoji = "✅" if "OK" in status else "❌"
        print(f"  {emoji} {phone} → {ip} | {status}")

    await asyncio.sleep(5)

    # views بعد
    c = make_client(admin_ss)
    await c.connect()
    ch = await c.get_entity(target)
    r = await c(functions.messages.GetMessagesViewsRequest(
        peer=ch, id=[msg_id], increment=False))
    after1 = r.views[0].views if r.views else "?"
    print(f"\n📊 views بعد از گروه ۱: {after1}")
    print(f"📈 اضافه شد: {int(after1) - int(before) if str(before).isdigit() else '?'}")

    # ═══ گروه ۲: ۱۰ اکانت بدون پروکسی (IP سرور) ═══
    print(f"\n{'━'*70}")
    print(f"  🅱️ گروه ۲: ۱۰ اکانت بدون پروکسی (همه از IP سرور)")
    print(f"{'━'*70}")

    sample_without = accounts[10:20]
    tasks = [view_no_proxy(acc["phone"], target, msg_id) for acc in sample_without]
    results = await asyncio.gather(*tasks)
    for phone, status in results:
        emoji = "✅" if "OK" in status else "❌"
        print(f"  {emoji} {phone} | {status}")

    await asyncio.sleep(5)

    c = make_client(admin_ss)
    await c.connect()
    ch = await c.get_entity(target)
    r = await c(functions.messages.GetMessagesViewsRequest(
        peer=ch, id=[msg_id], increment=False))
    after2 = r.views[0].views if r.views else "?"
    print(f"\n📊 views بعد از گروه ۲: {after2}")
    print(f"📈 گروه ۲ اضافه شد: {int(after2) - int(after1) if str(after1).isdigit() else '?'}")

    await c.disconnect()

    # ═══ نتیجه ═══
    print(f"\n{'═'*70}")
    print(f"  🎯 نتیجه نهایی")
    print(f"{'═'*70}")
    print(f"  شروع: {before}")
    print(f"  بعد گروه ۱ (با پروکسی): {after1} → +{int(after1) - int(before)}")
    print(f"  بعد گروه ۲ (بدون پروکسی): {after2} → +{int(after2) - int(after1)}")
    print(f"\n  💡 اگه گروه ۱ بیشتر از گروه ۲ بود → پروکسی‌ها کار می‌کنن ✅")
    print(f"  💡 اگه برابر بود → مشکل جای دیگه‌ست")


if __name__ == "__main__":
    asyncio.run(main())
