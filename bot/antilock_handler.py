"""Handler برای کنترل Anti-Lock — aiogram 3.x"""
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from core.anti_lock import ANTI_LOCK

router = Router()


@router.message(Command("al_status"))
async def cmd_antilock_status(message: Message):
    s = ANTI_LOCK.status()
    text = (
        f"🔒 <b>Anti-Lock Status</b>\n\n"
        f"وضعیت: {'⏸ paused' if s['paused'] else '▶️ active'}\n"
        f"زمان باقی‌مانده: {s['remaining']}s\n"
        f"تعداد pause: {s['pause_count']}\n"
        f"views اخیر: {s['recent_views']}\n"
    )
    await message.answer(text, parse_mode="HTML")


@router.message(Command("al_resume"))
async def cmd_antilock_resume(message: Message):
    ANTI_LOCK.resume()
    await message.answer("✅ Anti-Lock resume شد")


@router.message(Command("al_pause"))
async def cmd_antilock_pause(message: Message):
    ANTI_LOCK.pause()
    await message.answer(f"⏸ Anti-Lock pause شد — {ANTI_LOCK.pause_duration}s")
