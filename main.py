"""نقطه ورود ربات — aiogram 3 webhook / Python 3.14"""
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


# ── webhook ────────────────────────────────────────────
def _webhook_url() -> str:
    return f"{Config.WEBHOOK_BASE_URL}{Config.WEBHOOK_PATH}"


async def register_webhook(drop_pending: bool = False):
    """همیشه ثبت می‌کنه. تلگرام secret_token رو برنمی‌گردونه، پس نمیشه فهمید عوض شده یا نه."""
    kwargs = dict(url=_webhook_url(), drop_pending_updates=drop_pending)
    if Config.WEBHOOK_SECRET:
        kwargs["secret_token"] = Config.WEBHOOK_SECRET
    await bot.set_webhook(**kwargs)
    log.info(f"🔗 Webhook ثبت شد: {_webhook_url()}")


async def webhook_watchdog():
    """اگه webhook از بیرون پاک یا عوض بشه (مثلاً instance قدیمی موقع دیپلوی) دوباره ثبتش می‌کنه."""
    await asyncio.sleep(60)
    while True:
        try:
            info = await bot.get_webhook_info()
            if info.url != _webhook_url():
                log.warning(f"🔴 Webhook پاک/عوض شده بود ({info.url!r}) — ثبت مجدد")
                await register_webhook()
        except Exception as e:
            log.warning(f"webhook watchdog: {type(e).__name__}: {e}")
        await asyncio.sleep(120)


# ── boot در پس‌زمینه: پورت زود باز میشه، اکانت‌ها بعدش وصل میشن ──
async def boot_pool_and_listener():
    from core.pool import POOL
    try:
        log.info("🔌 اتصال همه اکانت‌ها...")
        await POOL.init()
        log.info(
            f"✅ Pool: {len(POOL.clients)}/{len(POOL.all_phones)} | "
            + " ".join(f"S{k}:{len(v)}" for k, v in POOL.shifts.items())
        )
    except Exception as e:
        log.exception(f"POOL.init: {e}")
    finally:
        POOL.ready.set()

    group_id  = db.get_target_group()
    auto_view = db.get_setting("auto_view_enabled", "1") == "1"

    if auto_view and group_id:
        try:
            from core.listener import GroupListener
            gl = GroupListener()
            dp["group_listener"]          = gl
            dp["group_listener_task"]     = asyncio.create_task(gl.start())
            dp["group_listener_watchdog"] = asyncio.create_task(group_listener_watchdog())
            log.info(f"👥 Group Listener روشن — group={group_id}")
        except Exception as e:
            log.exception(f"Group Listener: {e}")
    else:
        log.warning("⚠️ گروه هدف تنظیم نشده — ویو غیرفعال")

    mn = db.get_setting("shift_min_sec", Config.SHIFT_MIN_SEC)
    mx = db.get_setting("shift_max_sec", Config.SHIFT_MAX_SEC)
    for admin_id in Config.ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"🚀 <b>{Config.BOT_NAME}</b> روشن شد!\n"
                f"👥 اکانت: {len(POOL.clients)}/{len(POOL.all_phones)}\n"
                f"🎯 گروه هدف: <code>{db.fmt_group(group_id)}</code>\n"
                f"⏱️ شیفت: {int(mn)//60}-{int(mx)//60} دقیقه تصادفی\n"
                f"✅ شیفت فعال: {POOL.active_shift}\n"
                f"🌐 Webhook: {_webhook_url()}",
            )
        except Exception as e:
            log.warning(f"admin {admin_id}: {e}")
    log.info("✅ ربات آماده است")


# ── startup ────────────────────────────────────────────
async def on_startup(app: web.Application):
    errs = Config.validate()
    if errs:
        for e in errs:
            log.error(f"  - {e}")
        raise SystemExit(1)

    db.init_db()
    db.migrate_shifts()
    db.debug_log("main", "startup", "OK", Config.BOT_NAME)

    # webhook اول از همه، قبل از کار سنگین، تا ربات از همون ثانیه‌ی اول جواب بده
    await register_webhook(drop_pending=True)
    app["webhook_watchdog"] = asyncio.create_task(webhook_watchdog())
    app["boot_task"]        = asyncio.create_task(boot_pool_and_listener())


# ── shutdown ───────────────────────────────────────────
async def on_shutdown(app: web.Application):
    log.info("🛑 خاموش کردن...")
    for key in ("webhook_watchdog", "boot_task"):
        t = app.get(key)
        if t:
            t.cancel()
    # delete_webhook حذف شد — باعث می‌شد هر deploy نیاز به re-register داشته باشه
    # webhook روی Render با URL ثابت نیازی به حذف نداره

    obj = dp.get("group_listener")
    if obj:
        try:
            await asyncio.wait_for(obj.stop(), timeout=10)
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
async def health(request):
    return web.Response(text="OK", status=200)


def build_app() -> web.Application:
    app = web.Application()
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    # health check برای Render
    app.router.add_get("/", health)

    SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
        secret_token=Config.WEBHOOK_SECRET or None,
    ).register(app, path=Config.WEBHOOK_PATH)

    setup_application(app, dp, bot=bot)
    return app


if __name__ == "__main__":
    import os as _os
    # Render متغیر PORT رو خودش ست می‌کنه — اولویت با اون
    _port = int(_os.environ.get("PORT", Config.WEBHOOK_PORT))
    print(f"""
╔══════════════════════════════════════╗
║      🤖 {Config.BOT_NAME}
║      ادمین‌ها: {Config.ADMIN_IDS}
║      پورت: {_port}
╚══════════════════════════════════════╝
    """)
    web.run_app(
        build_app(),
        host="0.0.0.0",
        port=_port,
    )
