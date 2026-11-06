import asyncio
import sys
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
    msgs = await c.get_messages(ch, limit=5)
    print('📊 views ۵ پست آخر:')
    for m in msgs:
        r = await c(functions.messages.GetMessagesViewsRequest(
            peer=ch, id=[m.id], increment=False))
        v = r.views[0].views if r.views else '?'
        print(f'  ID={m.id} | views={v}')
    await c.disconnect()


asyncio.run(main())
