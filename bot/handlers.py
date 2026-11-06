"""هندلرهای کامل ربات — همه دکمه‌ها فعال"""
import sys
import asyncio
from pathlib import Path
from datetime import datetime, timedelta

from aiogram import types, Dispatcher
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters import Text
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import Config
from models import database as db
from bot.keyboards import (
    main_menu, status_menu, accounts_menu, accounts_list_kb,
    stats_menu, settings_menu, channel_menu, confirm_menu, cancel_menu,
    view_toggle_menu
)
from bot.states import AddAccount

_pending = {}
_pending_clients = _pending  # alias برای سازگاری


def is_admin(uid): return uid in Config.ADMIN_IDS


async def guard(msg):
    if not is_admin(msg.from_user.id):
        await msg.answer("⛔ دسترسی ندارید.")
        return False
    return True


# alias برای سازگاری
guard_admin = guard


# ═══════════════════════════════════════════════════════
# /start
# ═══════════════════════════════════════════════════════
async def cmd_start(msg):
    if not await guard(msg): return
    total = len(db.get_all_accounts())
    text = (
        f"🌟 <b>{Config.BOT_NAME}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👋 سلام!\n"
        f"🤖 این ربات سین‌زن حرفه‌ای شماست\n\n"
        f"📊 وضعیت سریع:\n"
        f"  👥 اکانت: <b>{total}</b>\n"
        f"  📢 کانال: <code>{Config.TARGET_CHANNEL_USERNAME}</code>\n"
        f"  ⏰ چرخش: هر ۲۵-۴۵ دقیقه\n\n"
        f"👇 از منو انتخاب کنید:"
    )
    await msg.answer(text, reply_markup=main_menu(), parse_mode="HTML")


async def cmd_help(msg):
    if not await guard(msg): return
    text = (
        "📖 <b>راهنمای استفاده</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "➕ <b>افزودن اکانت</b>: شماره رو وارد کن، کد رو بده، سشن ساخته می‌شه\n"
        "📊 <b>وضعیت زنده</b>: تعداد آنلاین/Flood/خطا\n"
        "👥 <b>مدیریت اکانت‌ها</b>: لیست، افزودن، چرخش، حذف\n"
        "📈 <b>آمار پیشرفته</b>: آمار ۲۴ ساعت، نمودار موفقیت\n"
        "🔄 <b>چرخش دستی</b>: تعویض فوری شیفت\n"
        "📢 <b>کانال هدف</b>: عضویت، چک عضویت\n"
        "⚙️ <b>تنظیمات</b>: طول شیفت، نگهبان، بکاپ\n\n"
        "💡 <b>نکات</b>:\n"
        "• بین هر اکانت ۳-۵ دقیقه صبر کن\n"
        "• اکانت جدید خودکار عضو کانال می‌شه\n"
        "• اگه Flood دیدی، ۱۰ دقیقه صبر کن"
    )
    await msg.answer(text, reply_markup=main_menu(), parse_mode="HTML")


# ═══════════════════════════════════════════════════════
# وضعیت زنده
# ═══════════════════════════════════════════════════════
def _status_text():
    counts = db.count_by_status()
    total = len(db.get_all_accounts())
    online = counts.get("online", 0)
    flood = counts.get("flood", 0)
    err = counts.get("error", 0)
    idle = counts.get("idle", 0)

    # نمودار متنی
    def bar(n, mx=total):
        if mx == 0: return "▱" * 10
        filled = int(n / mx * 10)
        return "▰" * filled + "▱" * (10 - filled)

    now = datetime.now().strftime("%H:%M:%S")
    text = (
        f"📊 <b>وضعیت زنده</b>  <code>{now}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🟢 آنلاین  {bar(online)}  <b>{online}</b>\n"
        f"💤 استراحت  {bar(idle)}  <b>{idle}</b>\n"
        f"🟡 Flood  {bar(flood)}  <b>{flood}</b>\n"
        f"🔴 خطا  {bar(err)}  <b>{err}</b>\n\n"
        f"📊 کل: <b>{total}</b> اکانت"
    )
    return text


async def show_status(msg):
    if not await guard(msg): return
    await msg.answer(_status_text(), reply_markup=status_menu(), parse_mode="HTML")


# ═══════════════════════════════════════════════════════
# مدیریت اکانت‌ها
# ═══════════════════════════════════════════════════════
async def show_view_toggle(msg):
    """نمایش منوی توقف/روشن ویو"""
    if not await guard(msg): return
    from core.listener import is_view_paused
    paused = is_view_paused()

    status_txt = "🔴 متوقف" if paused else "🟢 فعال"
    text = (
        f"🎬 <b>کنترل ویو زدن</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"وضعیت فعلی: <b>{status_txt}</b>\n\n"
        f"💡 اگه ویو رو خاموش کنی، ربات پیام‌ها رو نمی‌بینه\n"
        f"و سین نمی‌زنه. با روشن کردن دوباره فعال می‌شه.\n"
    )
    await msg.answer(text, reply_markup=view_toggle_menu(paused), parse_mode="HTML")


async def cb_view_toggle(cb, state):
    """Callback: توقف/روشن ویو"""
    from core.listener import set_view_paused, is_view_paused
    data = cb.data.split(":")[1] if ":" in cb.data else ""

    if data == "pause":
        set_view_paused(True)
        db.debug_log("handlers", "view_toggle", "OK", "⏸️ ویو متوقف شد")
        await cb.answer("⏸️ ویو متوقف شد", show_alert=True)
    elif data == "resume":
        set_view_paused(False)
        db.debug_log("handlers", "view_toggle", "OK", "▶️ ویو روشن شد")
        await cb.answer("▶️ ویو روشن شد", show_alert=True)
    elif data == "refresh":
        await cb.answer("🔄 بروزرسانی")

    # بروزرسانی متن
    paused = is_view_paused()
    status_txt = "🔴 متوقف" if paused else "🟢 فعال"
    text = (
        f"🎬 <b>کنترل ویو زدن</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"وضعیت فعلی: <b>{status_txt}</b>\n\n"
        f"💡 اگه ویو رو خاموش کنی، ربات پیام‌ها رو نمی‌بینه\n"
        f"و سین نمی‌زنه. با روشن کردن دوباره فعال می‌شه.\n"
    )
    try:
        await cb.message.edit_text(text, reply_markup=view_toggle_menu(paused), parse_mode="HTML")
    except Exception:
        pass


async def show_accounts(msg):
    if not await guard(msg): return
    total = len(db.get_all_accounts())
    counts = db.count_by_status()
    online = counts.get("online", 0)
    text = (
        f"👥 <b>مدیریت اکانت‌ها</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 تعداد: <b>{total}</b>\n"
        f"🟢 آنلاین: <b>{online}</b>\n\n"
        f"👇 گزینه مورد نظر:"
    )
    await msg.answer(text, reply_markup=accounts_menu(), parse_mode="HTML")


# ═══════════════════════════════════════════════════════
# آمار پیشرفته
# ═══════════════════════════════════════════════════════
async def show_stats(msg):
    if not await guard(msg): return
    text = (
        "📈 <b>آمار پیشرفته</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "👇 گزینه مورد نظر:"
    )
    await msg.answer(text, reply_markup=stats_menu(), parse_mode="HTML")


# ═══════════════════════════════════════════════════════
# کانال
# ═══════════════════════════════════════════════════════
async def show_channel(msg):
    if not await guard(msg): return
    text = (
        f"📢 <b>کانال هدف</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🎯 نام: <code>{Config.TARGET_CHANNEL_USERNAME}</code>\n"
        f"🆔 آیدی: <code>{Config.TARGET_CHANNEL_ID}</code>\n\n"
        f"👇 گزینه مورد نظر:"
    )
    await msg.answer(text, reply_markup=channel_menu(), parse_mode="HTML")


# ═══════════════════════════════════════════════════════
# تنظیمات
# ═══════════════════════════════════════════════════════
async def show_settings(msg):
    if not await guard(msg): return
    text = (
        "⚙️ <b>تنظیمات</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "👇 گزینه مورد نظر:"
    )
    await msg.answer(text, reply_markup=settings_menu(), parse_mode="HTML")


# ═══════════════════════════════════════════════════════
# چرخش دستی
# ═══════════════════════════════════════════════════════
async def manual_rotate(msg):
    if not await guard(msg): return
    try:
        from core.scheduler import AccountScheduler
        s = AccountScheduler()
        old = s._current_shift
        await s.rotate_now()
        new = s._current_shift
        await msg.answer(
            f"🔄 <b>چرخش انجام شد</b>\n\n"
            f"🅰️ شیفت قبلی: <b>{old}</b>\n"
            f"🅱️ شیفت جدید: <b>{new}</b>",
            parse_mode="HTML"
        )
    except Exception as e:
        await msg.answer(f"❌ خطا: {e}")


# ═══════════════════════════════════════════════════════
# /admin — پنل مخفی
# ═══════════════════════════════════════════════════════
async def cmd_admin(msg):
    if not await guard(msg): return
    await msg.answer("🔧 <b>پنل ادمین</b>\n\nهمه دسترسی‌ها فعاله.", parse_mode="HTML")


# ═══════════════════════════════════════════════════════
# Callback: منوی اصلی
# ═══════════════════════════════════════════════════════
async def cb_main_menu(cb, state):
    await state.finish()
    await cb.message.edit_text(
        "⚙️ منوی اصلی بازگشت.",
        reply_markup=main_menu() if False else None
    )
    try:
        await cb.message.edit_text(
            "👇 از منوی زیر انتخاب کنید:",
        )
    except Exception:
        pass
    await cb.answer("✅ برگشت به منو")


# ═══════════════════════════════════════════════════════
# Callback: وضعیت
# ═══════════════════════════════════════════════════════
async def cb_status(cb):
    data = cb.data.split(":")[1]
    if data == "refresh":
        await cb.message.edit_text(_status_text(), reply_markup=status_menu(), parse_mode="HTML")
        await cb.answer("🔄 بروزرسانی شد")
    else:
        # فیلتر خاص — نشون بده
        counts = db.count_by_status()
        n = counts.get(data, 0)
        emoji = {"online": "🟢", "idle": "💤", "error": "🔴", "flood": "🟡", "all": "📊"}.get(data, "❓")
        if data == "all":
            n = len(db.get_all_accounts())
        await cb.answer(f"{emoji} {n} اکانت", show_alert=True)


# ═══════════════════════════════════════════════════════
# Callback: مدیریت اکانت
# ═══════════════════════════════════════════════════════
async def cb_accounts(cb, state):
    d = cb.data.split(":", 2)

    # acc:list:PAGE
    if d[1] == "list":
        page = int(d[2]) if len(d) > 2 else 0
        accounts = db.get_all_accounts()
        if not accounts:
            await cb.message.edit_text(
                "📋 هیچ اکانتی نیست.",
                reply_markup=accounts_menu()
            )
        else:
            text = f"📋 <b>{len(accounts)} اکانت</b>\nصفحه {page+1}"
            await cb.message.edit_text(
                text,
                reply_markup=accounts_list_kb(accounts, page),
                parse_mode="HTML"
            )

    # acc:add
    elif d[1] == "add":
        await cb.message.edit_text(
            "➕ <b>افزودن اکانت جدید</b>\n\n"
            "شماره رو با فرمت بین‌المللی بفرست:\n"
            "<code>+989123456789</code>",
            reply_markup=cancel_menu(),
            parse_mode="HTML"
        )
        if state is not None:
            await state.set_state(AddAccount.waiting_phone.state)

    # acc:rotate
    elif d[1] == "rotate":
        from core.scheduler import AccountScheduler
        s = AccountScheduler()
        await s.rotate_now()
        await cb.answer("🔄 چرخش انجام شد", show_alert=True)
        await cb.message.edit_text(_status_text(), reply_markup=status_menu(), parse_mode="HTML")

    # acc:cleanup
    elif d[1] == "cleanup":
        await cb.answer("🧹 در حال پاک‌سازی...")
        conn = db.get_conn()
        try:
            r = conn.execute("UPDATE accounts SET status='idle', flood_until=NULL WHERE status='flood'")
            n = r.rowcount
        finally:
            conn.close()
        await cb.answer(f"✅ {n} اکانت آزاد شد", show_alert=True)

    # acc:backup
    elif d[1] == "backup":
        await cb.answer("💾 در حال بکاپ...")
        try:
            from core.backup import create_backup
            f = create_backup()
            await cb.answer(f"✅ بکاپ ساخته شد ({f.stat().st_size//1024}KB)", show_alert=True)
        except Exception as e:
            await cb.answer(f"❌ خطا: {e}", show_alert=True)

    # acc:info:ID
    elif d[1] == "info":
        acc_id = int(d[2])
        conn = db.get_conn()
        try:
            row = conn.execute("SELECT * FROM accounts WHERE id=?", (acc_id,)).fetchone()
        finally:
            conn.close()
        if row:
            a = dict(row)
            icon = {"online": "🟢", "flood": "🟡", "error": "🔴", "idle": "💤"}.get(a['status'], "⚪")
            text = (
                f"<b>📱 اکانت #{acc_id}</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"{icon} وضعیت: <b>{a['status']}</b>\n"
                f"🔢 شیفت: <b>{a['shift']}</b>\n"
                f"🌐 پورت: <code>{a.get('proxy_port') or '-'}</code>\n"
                f"📅 ساخته: {a['created_at'][:16]}\n"
            )
            if a.get('last_error'):
                text += f"\n⚠️ خطا: <code>{a['last_error'][:100]}</code>"
            await cb.message.edit_text(text, parse_mode="HTML")
        await cb.answer()

    # acc:noop
    elif d[1] == "noop":
        await cb.answer()

    await cb.answer() if d[1] not in ("noop",) else None


# ═══════════════════════════════════════════════════════
# Callback: آمار
# ═══════════════════════════════════════════════════════
async def cb_stats(cb):
    data = cb.data.split(":")[1]

    if data == "general":
        accounts = db.get_all_accounts()
        counts = db.count_by_status()
        text = (
            f"📊 <b>آمار کلی</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👥 کل اکانت: <b>{len(accounts)}</b>\n"
            f"🟢 آنلاین: <b>{counts.get('online', 0)}</b>\n"
            f"💤 استراحت: <b>{counts.get('idle', 0)}</b>\n"
            f"🟡 Flood: <b>{counts.get('flood', 0)}</b>\n"
            f"🔴 خطا: <b>{counts.get('error', 0)}</b>\n\n"
            f"🅰️ شیفت A: <b>{len([a for a in accounts if a['shift']=='A'])}</b>\n"
            f"🅱️ شیفت B: <b>{len([a for a in accounts if a['shift']=='B'])}</b>"
        )
        await cb.message.edit_text(text, reply_markup=stats_menu(), parse_mode="HTML")

    elif data == "daily":
        conn = db.get_conn()
        try:
            total = conn.execute(
                "SELECT COUNT(*) FROM debug_log WHERE step='new_post' AND message LIKE 'موفق%' "
                "AND created_at >= datetime('now', '-24 hours')"
            ).fetchone()[0]
            msgs = conn.execute(
                "SELECT COUNT(*) FROM debug_log WHERE step='new_msg' "
                "AND created_at >= datetime('now', '-24 hours')"
            ).fetchone()[0]
        finally:
            conn.close()
        text = (
            f"📈 <b>آمار ۲۴ ساعت</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📨 پیام‌های جدید: <b>{msgs}</b>\n"
            f"✅ سین‌های موفق: <b>{total}</b>\n"
        )
        await cb.message.edit_text(text, reply_markup=stats_menu(), parse_mode="HTML")

    elif data == "warp":
        import json
        try:
            hp = Config.BASE_DIR / "proxies" / "healthy_ports.json"
            data_json = json.loads(hp.read_text()) if hp.exists() else {}
            ips = data_json.get("ips", [])
            ports = data_json.get("port_to_ip", {})
            text = (
                f"🌐 <b>وضعیت WARP</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"🎯 IPهای یکتا: <b>{len(ips)}</b>\n"
                f"🔌 پورت‌های سالم: <b>{len(ports)}</b>\n\n"
            )
            for ip in ips[:10]:
                count = sum(1 for p, i in ports.items() if i == ip)
                text += f"  <code>{ip}</code> ({count} پورت)\n"
        except Exception as e:
            text = f"❌ خطا: {e}"
        await cb.message.edit_text(text, reply_markup=stats_menu(), parse_mode="HTML")

    elif data == "shift":
        from core.scheduler import AccountScheduler
        s = AccountScheduler()
        cur = s._current_shift or "?"
        nxt = s._next_swap_at.strftime("%H:%M:%S") if s._next_swap_at else "?"
        text = (
            f"🔄 <b>وضعیت چرخه</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🟢 شیفت فعلی: <b>{cur}</b>\n"
            f"⏰ swap بعدی: <b>{nxt}</b>\n"
            f"📊 بازه: <b>۲۵-۴۵ دقیقه تصادفی</b>"
        )
        await cb.message.edit_text(text, reply_markup=stats_menu(), parse_mode="HTML")

    elif data == "chart":
        conn = db.get_conn()
        try:
            rows = conn.execute(
                "SELECT substr(created_at, 1, 13) as h, "
                "SUM(CASE WHEN message LIKE 'موفق%' THEN 1 ELSE 0 END) as ok, "
                "COUNT(*) as total "
                "FROM debug_log WHERE step='new_post' AND created_at >= datetime('now', '-12 hours') "
                "GROUP BY h ORDER BY h"
            ).fetchall()
        finally:
            conn.close()
        text = "📉 <b>نمودار ۱۲ ساعت</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
        for r in rows:
            h = r["h"][11:13]
            ok = r["ok"] or 0
            bar = "▰" * min(ok, 20) + "▱" * max(0, 20 - min(ok, 20))
            text += f"<code>{h}:00</code> {bar} <b>{ok}</b>\n"
        await cb.message.edit_text(text, reply_markup=stats_menu(), parse_mode="HTML")

    await cb.answer()


# ═══════════════════════════════════════════════════════
# Callback: کانال
# ═══════════════════════════════════════════════════════
async def cb_channel(cb):
    data = cb.data.split(":")[1]

    if data == "join":
        await cb.answer("⏳ در حال عضویت همه اکانت‌ها...")
        asyncio.create_task(_join_all_task(cb))

    elif data == "check":
        await cb.answer("⏳ در حال بررسی...")
        asyncio.create_task(_check_join_task(cb))

    elif data == "info":
        await cb.answer(f"📢 {Config.TARGET_CHANNEL_USERNAME}", show_alert=True)

    await cb.answer()


async def _join_all_task(cb):
    try:
        from core.join_all import join_one
        accounts = db.get_all_accounts()
        joined = 0
        for a in accounts:
            _, r = await join_one(a["phone"])
            if r in ("joined", "already"):
                joined += 1
        await cb.message.answer(f"✅ {joined}/{len(accounts)} اکانت عضو کانال شدن")
    except Exception as e:
        await cb.message.answer(f"❌ {e}")


async def _check_join_task(cb):
    try:
        from core.engine import make_client
        accounts = db.get_all_accounts()
        joined = 0
        for a in accounts:
            try:
                ss = db.get_session(a["phone"])
                c = make_client(ss, phone=a["phone"])
                await asyncio.wait_for(c.connect(), timeout=15)
                target = Config.TARGET_CHANNEL_USERNAME or Config.TARGET_CHANNEL_ID
                entity = await c.get_entity(target)
                from telethon.tl.functions.channels import GetParticipantRequest
                await c(GetParticipantRequest(channel=entity, participant="me"))
                joined += 1
                await c.disconnect()
            except Exception:
                pass
        await cb.message.answer(f"✅ {joined}/{len(accounts)} عضو کانال")
    except Exception as e:
        await cb.message.answer(f"❌ {e}")


# ═══════════════════════════════════════════════════════
# Callback: تنظیمات
# ═══════════════════════════════════════════════════════
async def cb_settings(cb):
    data = cb.data.split(":")[1]
    if data == "shift":
        await cb.answer("⏱️ طول شیفت: ۲۵-۴۵ دقیقه تصادفی", show_alert=True)
    elif data == "active":
        await cb.answer(f"👥 تعداد فعال: {Config.SHIFT_SIZE}", show_alert=True)
    elif data == "guardian":
        await cb.answer("🛡️ نگهبان هر ۶۰ ثانیه چک می‌کنه", show_alert=True)
    elif data == "backup":
        await cb.answer("💾 هر ۱ ساعت بکاپ ساخته می‌شه", show_alert=True)
    elif data == "warp":
        await cb.answer("📊 وضعیت WARP در آمار پیشرفته", show_alert=True)
    await cb.answer()


# ═══════════════════════════════════════════════════════
# Confirm
# ═══════════════════════════════════════════════════════
async def cb_confirm(cb):
    d = cb.data.split(":")
    action = d[2] if len(d) > 2 else ""
    yes = d[1] == "yes"
    await cb.answer(f"{'✅' if yes else '❌'} {action}")


# ═══════════════════════════════════════════════════════
# FSM: افزودن اکانت
# ═══════════════════════════════════════════════════════
async def _join_channel(client):
    """عضویت خودکار در کانال"""
    try:
        target = Config.TARGET_CHANNEL_USERNAME or Config.TARGET_CHANNEL_ID
        if not target:
            return
        entity = await client.get_entity(target)
        try:
            from telethon.tl.functions.channels import JoinChannelRequest
            await client(JoinChannelRequest(entity))
            db.debug_log("handlers", "join", "OK", f"عضو {entity.title}")
        except Exception as e:
            err = str(e).lower()
            if "already" in err or "participant" in err:
                db.debug_log("handlers", "join", "SKIP", "قبلاً عضو")
            else:
                db.debug_log("handlers", "join", "WARN", f"{type(e).__name__}")
    except Exception as e:
        db.debug_log("handlers", "join", "WARN", f"{type(e).__name__}")


async def add_phone(msg, state):
    if not await guard_admin(msg):
        return
    phone = msg.text.strip()
    if not phone.startswith("+") or len(phone) < 10:
        await msg.answer("❌ فرمت اشتباه. مثال: <code>+989123456789</code>", parse_mode="HTML")
        return
    if db.get_account(phone):
        await msg.answer("⚠️ این شماره قبلاً ثبت شده.")
        await state.finish()
        return

    await msg.answer(f"📱 <code>{phone}</code>\n⏳ در حال ارسال کد...", parse_mode="HTML")

    c = None
    try:
        # ⚡ بدون WARP برای افزودن اکانت
        c = TelegramClient(StringSession(), Config.API_ID, Config.API_HASH)
        await asyncio.wait_for(c.connect(), timeout=20)
        db.debug_log("add", "connect", "OK", phone)

        sent = await asyncio.wait_for(c.send_code_request(phone), timeout=25)
        db.debug_log("add", "send_code", "OK", f"{phone} | hash={sent.phone_code_hash[:10]}")

        _pending_clients[msg.from_user.id] = c
        await state.update_data(phone=phone, phone_code_hash=sent.phone_code_hash)

        await msg.answer("✉️ <b>کد ارسال شد</b>\n\nکد رو با اعداد انگلیسی وارد کن:", parse_mode="HTML")
        # ═══ ست کردن state برای کد ═══
        if state is not None:
            try:
                await state.set_state(AddAccount.waiting_code.state)
            except Exception as e:
                db.debug_log("add", "state_code", "ERROR", str(e))

    except asyncio.TimeoutError:
        db.debug_log("add", "timeout", "ERROR", phone)
        await msg.answer("❌ <b>Timeout</b>\nسرور تلگرام پاسخ نداد. دوباره تلاش کن.", parse_mode="HTML")
        if c:
            try: await c.disconnect()
            except Exception: pass
        await state.finish()
    except Exception as e:
        err = str(e)
        db.debug_log("add", "error", "ERROR", f"{phone}: {err[:80]}")
        hint = ""
        if "PHONE_NUMBER_INVALID" in err:
            hint = "\n📌 شماره اشتباه"
        elif "PHONE_NUMBER_BANNED" in err:
            hint = "\n📌 شماره بن شده"
        elif "FLOOD" in err.upper():
            hint = "\n📌 ۵ دقیقه صبر کن"
        await msg.answer(f"❌ <b>خطا</b>: <code>{err[:150]}</code>{hint}", parse_mode="HTML")
        if c:
            try: await c.disconnect()
            except Exception: pass
        _pending_clients.pop(msg.from_user.id, None)
        await state.finish()



async def add_code(msg, state):
    if not await guard(msg): return
    code = msg.text.strip().replace("-", "").replace(" ", "")
    data = await state.get_data()
    phone = data["phone"]
    c = _pending.get(msg.from_user.id)
    if not c:
        await msg.answer("❌ کلاینت پیدا نشد. دوباره شروع کن.")
        await state.finish()
        return
    try:
        await c.sign_in(phone, code, phone_code_hash=data["phone_code_hash"])
        ss = c.session.save()
        me = await c.get_me()
        await _join_channel(c)
        await c.disconnect()
        _pending.pop(msg.from_user.id, None)
        acc_id = db.add_account(phone, ss)
        db.debug_log("handlers", "add", "OK", f"{phone}")

        await msg.answer(
            f"✅ <b>اکانت اضافه شد!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 نام: <b>{me.first_name}</b>\n"
            f"🆔 یوزرنیم: @{me.username or 'ندارد'}\n"
            f"🎫 شناسه: <code>{acc_id}</code>\n"
            f"👥 عضو کانال: ✅",
            reply_markup=main_menu(),
            parse_mode="HTML"
        )
        await state.finish()
    except SessionPasswordNeededError:
        await msg.answer("🔐 <b>رمز دو مرحله‌ای</b>\n\nرمز رو وارد کن:", parse_mode="HTML")
        if state is not None:
            await state.set_state(AddAccount.waiting_password.state)
    except Exception as e:
        await msg.answer(f"❌ خطا: <code>{e}</code>", parse_mode="HTML")
        try: await c.disconnect()
        except Exception: pass
        _pending.pop(msg.from_user.id, None)
        await state.finish()


async def add_password(msg, state):
    if not await guard(msg): return
    pwd = msg.text.strip()
    data = await state.get_data()
    phone = data["phone"]
    c = _pending.get(msg.from_user.id)
    if not c:
        await msg.answer("❌ کلاینت پیدا نشد.")
        await state.finish()
        return
    try:
        await c.sign_in(password=pwd)
        ss = c.session.save()
        me = await c.get_me()
        await _join_channel(c)
        await c.disconnect()
        _pending.pop(msg.from_user.id, None)
        acc_id = db.add_account(phone, ss)
        await msg.answer(
            f"✅ <b>اکانت با 2FA اضافه شد!</b>\n\n"
            f"👤 {me.first_name}\n"
            f"🎫 {acc_id}",
            reply_markup=main_menu(),
            parse_mode="HTML"
        )
        await state.finish()
    except Exception as e:
        await msg.answer(f"❌ خطا: <code>{e}</code>", parse_mode="HTML")
        try: await c.disconnect()
        except Exception: pass
        _pending.pop(msg.from_user.id, None)
        await state.finish()


async def add_cancel(cb, state):
    c = _pending.pop(cb.from_user.id, None)
    if c:
        try: await c.disconnect()
        except Exception: pass
    await state.finish()
    await cb.message.edit_text("❌ لغو شد.", reply_markup=accounts_menu())
    await cb.answer("لغو")


# ═══════════════════════════════════════════════════════
# ثبت هندلرها
# ═══════════════════════════════════════════════════════
def register_handlers(dp):
    # Commands
    dp.register_message_handler(cmd_start, commands=["start"])
    dp.register_message_handler(cmd_help, commands=["help"])
    dp.register_message_handler(cmd_admin, commands=["admin"])

    # Reply menu buttons — با اموجی (بدون مشکل فاصله)
    dp.register_message_handler(_add_account_start, Text(startswith="➕"))
    dp.register_message_handler(show_status, Text(startswith="📊"))
    dp.register_message_handler(show_accounts, Text(startswith="👥"))
    dp.register_message_handler(show_stats, Text(startswith="📈"))
    dp.register_message_handler(show_view_toggle, Text(startswith="🎬"))
    dp.register_message_handler(manual_rotate, Text(startswith="🔄"))
    dp.register_message_handler(show_settings, Text(startswith="⚙️"))
    dp.register_message_handler(show_channel, Text(startswith="📢"))
    dp.register_message_handler(cmd_help, Text(startswith="❓"))

    # Callbacks
    dp.register_callback_query_handler(cb_main_menu, text="menu:main", state="*")
    dp.register_callback_query_handler(cb_status, text_startswith="status:")
    dp.register_callback_query_handler(cb_accounts, text_startswith="acc:", state="*")
    dp.register_callback_query_handler(cb_stats, text_startswith="stats:")
    dp.register_callback_query_handler(cb_channel, text_startswith="ch:")
    dp.register_callback_query_handler(cb_view_toggle, text_startswith="view:", state="*")
    dp.register_callback_query_handler(cb_settings, text_startswith="set:")
    dp.register_callback_query_handler(cb_confirm, text_startswith="cfm:")
    dp.register_callback_query_handler(add_cancel, text="add:cancel", state="*")

    # FSM
    dp.register_message_handler(add_phone, state=AddAccount.waiting_phone)
    dp.register_message_handler(add_code, state=AddAccount.waiting_code)
    dp.register_message_handler(add_password, state=AddAccount.waiting_password)


async def _add_account_start(msg, state=None):
    """افزودن اکانت از منوی اصلی"""
    if not await guard(msg): return
    from aiogram.dispatcher import FSMContext
    if state is not None:
        await state.set_state(AddAccount.waiting_phone.state)
    await msg.answer(
        "➕ <b>افزودن اکانت جدید</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "شماره رو با فرمت بین‌المللی بفرست:\n"
        "<code>+989123456789</code>\n\n"
        "💡 اکانت خودکار عضو کانال می‌شه.",
        reply_markup=cancel_menu(),
        parse_mode="HTML"
    )
