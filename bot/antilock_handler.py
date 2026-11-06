"""Handler برای کنترل Anti-Lock از ربات"""
from aiogram import types
from core.anti_lock import ANTI_LOCK


async def cmd_antilock_status(message: types.Message):
    """وضعیت anti-lock"""
    s = ANTI_LOCK.status()
    text = (
        f"🔒 <b>Anti-Lock Status</b>\n\n"
        f"وضعیت: {'⏸ paused' if s['paused'] else '▶️ active'}\n"
        f"زمان باقی‌مانده: {s['remaining']}s\n"
        f"تعداد pause: {s['pause_count']}\n"
        f"views اخیر: {s['recent_views']}\n"
    )
    await message.answer(text, parse_mode="HTML")


async def cmd_antilock_resume(message: types.Message):
    """resume دستی"""
    ANTI_LOCK.resume()
    await message.answer("✅ Anti-Lock resum شد")


async def cmd_antilock_pause(message: types.Message):
    """pause دستی"""
    ANTI_LOCK.pause()
    await message.answer(f"⏸ Anti-Lock pause شد — {ANTI_LOCK.pause_duration}s")


def register_antilock(dp):
    dp.register_message_handler(cmd_antilock_status, commands=["al_status"])
    dp.register_message_handler(cmd_antilock_resume, commands=["al_resume"])
    dp.register_message_handler(cmd_antilock_pause, commands=["al_pause"])
