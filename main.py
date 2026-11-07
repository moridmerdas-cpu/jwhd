"""نقطه ورود ربات — aiogram 3.x"""
import asyncio
import logging
import sys
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

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


async def listener_watchdog():
    await asyncio.sleep(20)
    while True:
        try:
            t = dp.get("listener_task")
            if t is None or t.done():
                log.warning("🔴 Listener مرده — راه‌اندازی مجدد")
                from core.listener import ChannelListener
                l = ChannelListener()
                dp["listener"]       = l
                dp["listener_task"]  = asyncio.create_task(l.start())
        except Exception as e:
            log.exception(f"watchdog: {e}")
        await asyncio.sleep(30)


async def on_startup():
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

    # Pre-warm entity cache
    log.info("🔥 Pre-warming entity cache...")
    try:
        from core.listener import _ENTITY_CACHE
        target = Config.TARGET_GROUP_ID

        async def warm(phone):
            try:
                c = POOL.clients.get(phone)
                if c is None: return False
                ent = await asyncio.wait_for(c.get_entity(target), timeout=10)
                _ENTITY_CACHE[(phone, str(target))] = ent
                return True
            except Exception:
                return False

        sem = asyncio.Semaphore(20)
        async def one(p):
            async with sem: return await warm(p)

        results = await asyncio.gather(
            *[one(p) for p in POOL.all_phones if p in POOL.clients],
            return_exceptions=True,
        )
        ok_count = sum(1 for r in results if r is True)
        log.info(f"🔥 Entity cache: {ok_count}/{len(POOL.clients)} آماده")
    except Exception as e:
        log.warning(f"Prewarm: {e}")

    # Listener
    if Config.AUTO_VIEW_ENABLED and Config.TARGET_GROUP_ID:
        try:
            from core.listener import ChannelListener
            l = ChannelListener()
            dp["listener"]                = l
            dp["listener_task"]           = asyncio.create_task(l.start())
            dp["listener_watchdog_task"]  = asyncio.create_task(listener_watchdog())
            log.info("👂 Listener + Watchdog روشن")
        except Exception as e:
            log.exception(f"Listener: {e}")

    for admin_id in Config.ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"🚀 <b>{Config.BOT_NAME}</b> روشن شد!\n"
                f"👥 اکانت: {len(POOL.clients)}/{len(POOL.all_phones)}\n"
                f"✅ شیفت فعال: {POOL.active_shift}",
            )
        except Exception as e:
            log.warning(f"admin {admin_id}: {e}")

    log.info("✅ ربات آماده است")


async def on_shutdown():
    log.info("🛑 خاموش کردن...")
    try:
        listener = dp.get("listener")
        if listener:
            try: await asyncio.wait_for(listener.stop(), timeout=10)
            except Exception: pass
        scheduler = dp.get("scheduler")
        if scheduler:
            try: scheduler.stop()
            except Exception: pass
        from core.pool import POOL
        try: await asyncio.wait_for(POOL.close_all(), timeout=15)
        except Exception: pass
    except Exception as e:
        log.exception(f"shutdown: {e}")
    try: db.debug_log("main", "shutdown", "OK", "خاموش")
    except Exception: pass
    log.info("🛑 ربات خاموش شد")


async def main():
    print(f"""
╔══════════════════════════════════════╗
║      🤖 {Config.BOT_NAME}
║      ادمین‌ها: {Config.ADMIN_IDS}
╚══════════════════════════════════════╝
    """)
    register_handlers(dp)
    await on_startup()
    try:
        await dp.start_polling(bot, skip_updates=True)
    finally:
        await on_shutdown()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("متوقف شد توسط کاربر")
