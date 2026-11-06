"""تست multi-id در GetMessagesViewsRequest"""
import asyncio, sys
sys.path.insert(0, '/root/tg_master_bot')
from config import Config
from models import database as db
from core.engine import make_client
from telethon import functions


async def main():
    db.init_db()
    admin = db.get_all_accounts()[0]
    c = make_client(db.get_session(admin['phone']))
    await c.connect()
    target = Config.TARGET_CHANNEL_USERNAME or Config.TARGET_CHANNEL_ID
    ch = await c.get_entity(target)

    # آخرین ۱۰ پست
    msgs = await c.get_messages(ch, limit=10)
    ids = [m.id for m in msgs]
    print(f'📋 IDs: {ids}')
    print(f'📋 تعداد: {len(ids)}')

    # views قبل
    print('\n⏳ خواندن views قبل...')
    r = await c(functions.messages.GetMessagesViewsRequest(
        peer=ch, id=ids, increment=False))
    print(f'  تعداد نتایج: {len(r.views)}')
    print(f'  نمونه اول: views={r.views[0].views}, forwards={r.views[0].forwards}')

    before = [v.views for v in r.views]
    print(f'  قبل: {before}')

    # ═══ تست multi-id با increment=True ═══
    print('\n🧪 تست multi-id با increment:')
    try:
        r2 = await c(functions.messages.GetMessagesViewsRequest(
            peer=ch, id=ids, increment=True))
        after = [v.views for v in r2.views]
        print(f'  ✅ نتیجه: {after}')
    except Exception as e:
        print(f'  ❌ {type(e).__name__}: {e}')

    await asyncio.sleep(8)

    # views نهایی
    print('\n⏳ خواندن views نهایی...')
    r = await c(functions.messages.GetMessagesViewsRequest(
        peer=ch, id=ids, increment=False))
    final = [v.views for v in r.views]
    print(f'  بعد: {final}')

    print('\n═══════════════════════════════════════')
    print('  📊 مقایسه:')
    for i, (b, a, f) in enumerate(zip(before, final, [0]*len(before))):
        delta = f - b
        print(f'  ID={ids[i]} | قبل: {b} → بعد: {f} | Δ={delta}')
    print('═══════════════════════════════════════')

    if any(f > b for b, f in zip(before, final)):
        print('\n✅ multi-id کار می‌کنه! می‌تونیم ۱۰ برابر سریع‌تر کنیم.')
    else:
        print('\n⚠️ multi-id کار نکرد، باید راه دیگه‌ای بریم.')

    await c.disconnect()


asyncio.run(main())
