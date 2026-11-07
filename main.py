"""نقطه ورود ربات — aiogram 3 webhook / Python 3.14 / group-only"""
import asyncio
import logging
import sys
from pathlib import Path

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.webhook.aiohttp_server import (
    SimpleRequestHandler,
    setup_application,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import Config
from models import database as db
from bot.handlers import register_handlers

logging.basicConfig(
    level=getattr(logging, Config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[
        logging.FileHandler(Config.LOG_DIR / "bot.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("master_bot")

bot = Bot(
    token=Config.BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
storage = MemoryStorage()
dp      = Dispatcher(storage=storage)
register_handlers(dp)


# ── watchdog: Group Listener ───────────────────────────
async def group_listener_watchdog():
    await asyncio.sleep(25)
    while True:
        try:
            t = dp.get("group_listener_task")
            if t is None or t.done():
                log.warning("🔴 Group Listener مرده — راه‌اندازی مجدد")
                from core.listener import GroupListener
                gl = GroupListener()
                dp["group_listener"]      = gl
                dp["group_listener_task"] = asyncio.create_task(gl.start())
        except Exception as e:
            log.exception(f"group watchdog: {e}")
        await asyncio.sleep(30)


# ── startup ────────────────────────────────────────────
async def on_startup(app: web.Application):
    errs = Config.validate()
    if errs:
        for e in errs:
            log.error(f"  - {e}")
        raise SystemExit(1)

    db.init_db()
    db.debug_log("main", "startup", "OK", Config.BOT_NAME)

    from core.pool import POOL
    log.info("🔌 اتصال همه اکانت‌ها...")
    await POOL.init()
    log.info(
        f"✅ Pool: {len(POOL.clients)}/{len(POOL.all_phones)} | "
        + " ".join(f"S{k}:{len(v)}" for k, v in POOL.shifts.items())
    )

    # Pre-warm: group entity cache
    if Config.TARGET_GROUP_ID:
        log.info("🔥 Pre-warming group entity cache...")
        try:
            from core.listener import _GROUP_ENTITY_CACHE
            sem = asyncio.Semaphore(20)

            async def warm(phone):
                try:
                    c = POOL.clients.get(phone)
                    if c is None:
                        return False
                    ent = await asyncio.wait_for(
                        c.get_entity(Config.TARGET_GROUP_ID), timeout=10)
                    _GROUP_ENTITY_CACHE[(phone, str(Config.TARGET_GROUP_ID))] = ent
                    return True
                except Exception:
                    return False

            async def one(p):
                async with sem:
                    return await warm(p)

            results  = await asyncio.gather(
                *[one(p) for p in POOL.all_phones if p in POOL.clients],
                return_exceptions=True,
            )
            ok_count = sum(1 for r in results if r is True)
            log.info(f"🔥 Group entity cache: {ok_count}/{len(POOL.clients)} آماده")
        except Exception as e:
            log.warning(f"Prewarm: {e}")

    # Group Listener — تنها listener
    if Config.AUTO_VIEW_ENABLED and Config.TARGET_GROUP_ID:
        try:
            from core.listener import GroupListener
            gl = GroupListener()
            dp["group_listener"]               = gl
            dp["group_listener_task"]          = asyncio.create_task(gl.start())
            dp["group_listener_watchdog_task"] = asyncio.create_task(group_listener_watchdog())
            log.info(f"👥 Group Listener روشن — group={Config.TARGET_GROUP_ID}")
        except Exception as e:
            log.exception(f"Group Listener: {e}")
    else:
        log.warning("⚠️ TARGET_GROUP_ID تنظیم نشده — listener غیرفعال")

    webhook_url = f"{Config.WEBHOOK_BASE_URL}{Config.WEBHOOK_PATH}"
    await bot.set_webhook(
        url=webhook_url,
        secret_token=Config.WEBHOOK_SECRET,
        drop_pending_updates=True,
    )
    log.info(f"🔗 Webhook ثبت شد: {webhook_url}")

    for admin_id in Config.ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"🚀 <b>{Config.BOT_NAME}</b> روشن شد!\n"
                f"👥 اکانت: {len(POOL.clients)}/{len(POOL.all_phones)}\n"
                f"S1: {len(POOL.shifts.get(1, []))} | "
                f"S2: {len(POOL.shifts.get(2, []))} | "
                f"S3: {len(POOL.shifts.get(3, []))} | "
                f"S4: {len(POOL.shifts.get(4, []))}\n"
                f"✅ شیفت فعال: {POOL.active_shift}\n"
                f"🌐 Webhook: {webhook_url}\n"
                f"👥 گروه: <code>{Config.TARGET_GROUP_ID}</code>",
            )
        except Exception as e:
            log.warning(f"admin {admin_id}: {e}")

    log.info("✅ ربات آماده است")


# ── shutdown ───────────────────────────────────────────
async def on_shutdown(app: web.Application):
    log.info("🛑 خاموش کردن...")
    try:
        await bot.delete_webhook()
    except Exception:
        pass

    gl = dp.get("group_listener")
    if gl:
        try:
            await asyncio.wait_for(gl.stop(), timeout=10)
        except Exception:
            pass

    try:
        from core.pool import POOL
        await asyncio.wait_for(POOL.close_all(), timeout=15)
    except Exception:
        pass

    try:
        db.debug_log("main", "shutdown", "OK", "خاموش")
    except Exception:
        pass

    await bot.session.close()
    log.info("🛑 ربات خاموش شد")


# ── aiohttp app ────────────────────────────────────────
def build_app() -> web.Application:
    app = web.Application()
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
        secret_token=Config.WEBHOOK_SECRET,
    ).register(app, path=Config.WEBHOOK_PATH)

    setup_application(app, dp, bot=bot)
    return app


if __name__ == "__main__":
    print(f"""
╔══════════════════════════════════════╗
║      🤖 {Config.BOT_NAME}
║      ادمین‌ها: {Config.ADMIN_IDS}
║      پورت: {Config.WEBHOOK_PORT}
║      گروه: {Config.TARGET_GROUP_ID}
╚══════════════════════════════════════╝
    """)
    web.run_app(
        build_app(),
        host=Config.WEBHOOK_HOST,
        port=Config.WEBHOOK_PORT,
    )
