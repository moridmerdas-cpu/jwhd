"""هندلرهای کامل ربات — aiogram 3.x"""
import sys
import asyncio
from pathlib import Path
from datetime import datetime, timedelta

from aiogram import Router, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from telethon import TelegramClient, functions
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError
from telethon.tl.functions.account import GetPasswordRequest
from telethon.crypto import compute_check

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import Config
from models import database as db
from bot.keyboards import (
    main_menu, status_menu, accounts_menu, accounts_list_kb,
    stats_menu, settings_menu, channel_menu, confirm_menu,
    cancel_menu, view_toggle_menu,
)
from bot.states import AddAccount

router = Router()

_pending: dict = {}


def is_admin(uid): return uid in Config.ADMIN_IDS


async def guard(msg: Message) -> bool:
    if not is_admin(msg.from_user.id):
        await msg.answer("⛔ دسترسی ندارید.")
        return False
    return True


# ═══ /start ═══
@router.message(Command("start"))
async def cmd_start(msg: Message):
    if not await guard(msg): return
    total = len(db.get_all_accounts())
    await msg.answer(
        f"🌟 <b>{Config.BOT_NAME}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👋 سلام!\n🤖 این ربات سین‌زن حرفه‌ای شماست\n\n"
        f"📊 وضعیت سریع:\n"
        f"  👥 اکانت: <b>{total}</b>\n"
        f"  📢 کانال: <code>{Config.TARGET_CHANNEL_USERNAME}</code>\n"
        f"  ⏰ چرخش: هر ۲۵-۴۵ دقیقه\n\n"
        f"👇 از منو انتخاب کنید:",
        reply_markup=main_menu(), parse_mode="HTML"
    )


@router.message(Command("help"))
@router.message(F.text.startswith("❓"))
async def cmd_help(msg: Message):
    if not await guard(msg): return
    await msg.answer(
        "📖 <b>راهنمای استفاده</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "➕ <b>افزودن اکانت</b>: شماره رو وارد کن، کد رو بده\n"
        "📊 <b>وضعیت زنده</b>: تعداد آنلاین/Flood/خطا\n"
        "👥 <b>مدیریت اکانت‌ها</b>: لیست، افزودن، چرخش، حذف\n"
        "📈 <b>آمار پیشرفته</b>: آمار ۲۴ ساعت\n"
        "🔄 <b>چرخش دستی</b>: تعویض فوری شیفت\n"
        "📢 <b>کانال هدف</b>: عضویت، چک عضویت\n"
        "⚙️ <b>تنظیمات</b>: طول شیفت، نگهبان، بکاپ",
        reply_markup=main_menu(), parse_mode="HTML"
    )


@router.message(Command("admin"))
async def cmd_admin(msg: Message):
    if not await guard(msg): return
    await msg.answer("🔧 <b>پنل ادمین</b>\n\nهمه دسترسی‌ها فعاله.", parse_mode="HTML")


# ═══ وضعیت زنده ═══
def _status_text():
    counts = db.count_by_status()
    total  = len(db.get_all_accounts())
    online = counts.get("online", 0)
    flood  = counts.get("flood",  0)
    err    = counts.get("error",  0)
    idle   = counts.get("idle",   0)
    def bar(n, mx=total):
        if mx == 0: return "▱" * 10
        filled = int(n / mx * 10)
        return "▰" * filled + "▱" * (10 - filled)
    now = datetime.now().strftime("%H:%M:%S")
    return (
        f"📊 <b>وضعیت زنده</b>  <code>{now}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🟢 آنلاین   {bar(online)}  <b>{online}</b>\n"
        f"💤 استراحت  {bar(idle)}    <b>{idle}</b>\n"
        f"🟡 Flood    {bar(flood)}   <b>{flood}</b>\n"
        f"🔴 خطا      {bar(err)}     <b>{err}</b>\n\n"
        f"📊 کل: <b>{total}</b> اکانت"
    )


@router.message(F.text.startswith("📊"))
async def show_status(msg: Message):
    if not await guard(msg): return
    await msg.answer(_status_text(), reply_markup=status_menu(), parse_mode="HTML")


# ═══ ویو toggle ═══
@router.message(F.text.startswith("🎬"))
async def show_view_toggle(msg: Message):
    if not await guard(msg): return
    from core.listener import is_view_paused
    paused = is_view_paused()
    status_txt = "🔴 متوقف" if paused else "🟢 فعال"
    await msg.answer(
        f"🎬 <b>کنترل ویو زدن</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"وضعیت فعلی: <b>{status_txt}</b>\n",
        reply_markup=view_toggle_menu(paused), parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("view:"))
async def cb_view_toggle(cb: CallbackQuery):
    from core.listener import set_view_paused, is_view_paused
    action = cb.data.split(":")[1]
    if action == "pause":
        set_view_paused(True)
        await cb.answer("⏸️ ویو متوقف شد", show_alert=True)
    elif action == "resume":
        set_view_paused(False)
        await cb.answer("▶️ ویو روشن شد", show_alert=True)
    else:
        await cb.answer("🔄 بروزرسانی")
    paused = is_view_paused()
    status_txt = "🔴 متوقف" if paused else "🟢 فعال"
    try:
        await cb.message.edit_text(
            f"🎬 <b>کنترل ویو زدن</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"وضعیت فعلی: <b>{status_txt}</b>\n",
            reply_markup=view_toggle_menu(paused), parse_mode="HTML"
        )
    except Exception:
        pass


# ═══ مدیریت اکانت‌ها ═══
@router.message(F.text.startswith("👥"))
async def show_accounts(msg: Message):
    if not await guard(msg): return
    total  = len(db.get_all_accounts())
    online = db.count_by_status().get("online", 0)
    await msg.answer(
        f"👥 <b>مدیریت اکانت‌ها</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 تعداد: <b>{total}</b>\n🟢 آنلاین: <b>{online}</b>\n\n👇 گزینه مورد نظر:",
        reply_markup=accounts_menu(), parse_mode="HTML"
    )


# ═══ آمار ═══
@router.message(F.text.startswith("📈"))
async def show_stats(msg: Message):
    if not await guard(msg): return
    await msg.answer("📈 <b>آمار پیشرفته</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n👇 گزینه مورد نظر:",
                     reply_markup=stats_menu(), parse_mode="HTML")


# ═══ کانال ═══
@router.message(F.text.startswith("📢"))
async def show_channel(msg: Message):
    if not await guard(msg): return
    await msg.answer(
        f"📢 <b>کانال هدف</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🎯 نام: <code>{Config.TARGET_CHANNEL_USERNAME}</code>\n"
        f"🆔 آیدی: <code>{Config.TARGET_CHANNEL_ID}</code>\n\n"
        f"👇 گزینه مورد نظر:",
        reply_markup=channel_menu(), parse_mode="HTML"
    )


# ═══ تنظیمات ═══
@router.message(F.text.startswith("⚙️"))
async def show_settings(msg: Message):
    if not await guard(msg): return
    await msg.answer("⚙️ <b>تنظیمات</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n👇 گزینه مورد نظر:",
                     reply_markup=settings_menu(), parse_mode="HTML")


# ═══ چرخش دستی ═══
@router.message(F.text.startswith("🔄"))
async def manual_rotate(msg: Message):
    if not await guard(msg): return
    try:
        from core.scheduler import AccountScheduler
        s = AccountScheduler()
        old = s._current_shift
        await s.rotate_now()
        new = s._current_shift
        await msg.answer(
            f"🔄 <b>چرخش انجام شد</b>\n\n"
            f"🅰️ شیفت قبلی: <b>{old}</b>\n🅱️ شیفت جدید: <b>{new}</b>",
            parse_mode="HTML"
        )
    except Exception as e:
        await msg.answer(f"❌ خطا: {e}")


# ═══ افزودن اکانت از منوی اصلی ═══
@router.message(F.text.startswith("➕"))
async def add_account_start(msg: Message, state: FSMContext):
    if not await guard(msg): return
    await state.set_state(AddAccount.waiting_phone)
    await msg.answer(
        "➕ <b>افزودن اکانت جدید</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "شماره رو با فرمت بین‌المللی بفرست:\n"
        "<code>+989123456789</code>\n\n"
        "💡 اکانت خودکار عضو کانال می‌شه.",
        reply_markup=cancel_menu(), parse_mode="HTML"
    )


# ═══ Callbacks ═══
@router.callback_query(F.data == "menu:main")
async def cb_main_menu(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await cb.message.edit_text("👇 از منوی زیر انتخاب کنید:")
    except Exception:
        pass
    await cb.answer("✅ برگشت به منو")


@router.callback_query(F.data.startswith("status:"))
async def cb_status(cb: CallbackQuery):
    data = cb.data.split(":")[1]
    if data == "refresh":
        await cb.message.edit_text(_status_text(), reply_markup=status_menu(), parse_mode="HTML")
        await cb.answer("🔄 بروزرسانی شد")
    else:
        counts = db.count_by_status()
        n = len(db.get_all_accounts()) if data == "all" else counts.get(data, 0)
        emoji = {"online": "🟢", "idle": "💤", "error": "🔴", "flood": "🟡", "all": "📊"}.get(data, "❓")
        await cb.answer(f"{emoji} {n} اکانت", show_alert=True)


@router.callback_query(F.data.startswith("acc:"))
async def cb_accounts(cb: CallbackQuery, state: FSMContext):
    d = cb.data.split(":", 2)
    action = d[1]

    if action == "list":
        page = int(d[2]) if len(d) > 2 else 0
        accounts = db.get_all_accounts()
        if not accounts:
            await cb.message.edit_text("📋 هیچ اکانتی نیست.", reply_markup=accounts_menu())
        else:
            await cb.message.edit_text(
                f"📋 <b>{len(accounts)} اکانت</b>\nصفحه {page+1}",
                reply_markup=accounts_list_kb(accounts, page), parse_mode="HTML"
            )

    elif action == "add":
        await cb.message.edit_text(
            "➕ <b>افزودن اکانت جدید</b>\n\nشماره رو با فرمت بین‌المللی بفرست:\n<code>+989123456789</code>",
            reply_markup=cancel_menu(), parse_mode="HTML"
        )
        await state.set_state(AddAccount.waiting_phone)

    elif action == "rotate":
        from core.scheduler import AccountScheduler
        await AccountScheduler().rotate_now()
        await cb.answer("🔄 چرخش انجام شد", show_alert=True)
        await cb.message.edit_text(_status_text(), reply_markup=status_menu(), parse_mode="HTML")

    elif action == "cleanup":
        conn = db.get_conn()
        try:
            r = conn.execute("UPDATE accounts SET status='idle', flood_until=NULL WHERE status='flood'")
            n = r.rowcount
            conn.commit()
        finally:
            conn.close()
        await cb.answer(f"✅ {n} اکانت آزاد شد", show_alert=True)

    elif action == "backup":
        try:
            from core.backup import create_backup
            f = create_backup()
            await cb.answer(f"✅ بکاپ ساخته شد ({f.stat().st_size//1024}KB)", show_alert=True)
        except Exception as e:
            await cb.answer(f"❌ خطا: {e}", show_alert=True)

    elif action == "info":
        acc_id = int(d[2])
        conn = db.get_conn()
        try:
            row = conn.execute("SELECT * FROM accounts WHERE id=?", (acc_id,)).fetchone()
        finally:
            conn.close()
        if row:
            a = dict(row)
            icon = {"online": "🟢", "flood": "🟡", "error": "🔴", "idle": "💤"}.get(a["status"], "⚪")
            text = (
                f"<b>📱 اکانت #{acc_id}</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"{icon} وضعیت: <b>{a['status']}</b>\n"
                f"🔢 شیفت: <b>{a['shift']}</b>\n"
                f"🌐 پورت: <code>{a.get('proxy_port') or '-'}</code>\n"
                f"📅 ساخته: {a['created_at'][:16]}\n"
            )
            if a.get("last_error"):
                text += f"\n⚠️ خطا: <code>{a['last_error'][:100]}</code>"
            await cb.message.edit_text(text, parse_mode="HTML")

    elif action != "noop":
        await cb.answer()

    if action != "noop":
        try:
            await cb.answer()
        except Exception:
            pass


@router.callback_query(F.data.startswith("stats:"))
async def cb_stats(cb: CallbackQuery):
    data = cb.data.split(":")[1]

    if data == "general":
        accounts = db.get_all_accounts()
        counts   = db.count_by_status()
        text = (
            f"📊 <b>آمار کلی</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👥 کل: <b>{len(accounts)}</b>\n"
            f"🟢 آنلاین: <b>{counts.get('online',0)}</b>\n"
            f"💤 استراحت: <b>{counts.get('idle',0)}</b>\n"
            f"🟡 Flood: <b>{counts.get('flood',0)}</b>\n"
            f"🔴 خطا: <b>{counts.get('error',0)}</b>"
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
        await cb.message.edit_text(
            f"📈 <b>آمار ۲۴ ساعت</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📨 پیام‌های جدید: <b>{msgs}</b>\n✅ سین‌های موفق: <b>{total}</b>",
            reply_markup=stats_menu(), parse_mode="HTML"
        )

    elif data == "warp":
        import json
        try:
            hp = Config.BASE_DIR / "proxies" / "healthy_ports.json"
            d2 = json.loads(hp.read_text()) if hp.exists() else {}
            ips   = d2.get("ips", [])
            ports = d2.get("port_to_ip", {})
            text  = (
                f"🌐 <b>وضعیت WARP</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"🎯 IPهای یکتا: <b>{len(ips)}</b>\n🔌 پورت‌های سالم: <b>{len(ports)}</b>\n\n"
            )
            for ip in ips[:10]:
                count = sum(1 for p, i in ports.items() if i == ip)
                text += f"  <code>{ip}</code> ({count} پورت)\n"
        except Exception as e:
            text = f"❌ خطا: {e}"
        await cb.message.edit_text(text, reply_markup=stats_menu(), parse_mode="HTML")

    elif data == "shift":
        from core.scheduler import AccountScheduler
        s   = AccountScheduler()
        cur = s._current_shift or "?"
        nxt = s._next_swap_at.strftime("%H:%M:%S") if s._next_swap_at else "?"
        await cb.message.edit_text(
            f"🔄 <b>وضعیت چرخه</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🟢 شیفت فعلی: <b>{cur}</b>\n⏰ swap بعدی: <b>{nxt}</b>",
            reply_markup=stats_menu(), parse_mode="HTML"
        )

    elif data == "chart":
        conn = db.get_conn()
        try:
            rows = conn.execute(
                "SELECT substr(created_at,1,13) as h, "
                "SUM(CASE WHEN message LIKE 'موفق%' THEN 1 ELSE 0 END) as ok "
                "FROM debug_log WHERE step='new_post' AND created_at >= datetime('now','-12 hours') "
                "GROUP BY h ORDER BY h"
            ).fetchall()
        finally:
            conn.close()
        text = "📉 <b>نمودار ۱۲ ساعت</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
        for r in rows:
            h  = r["h"][11:13]
            ok = r["ok"] or 0
            bar = "▰" * min(ok, 20) + "▱" * max(0, 20 - min(ok, 20))
            text += f"<code>{h}:00</code> {bar} <b>{ok}</b>\n"
        await cb.message.edit_text(text, reply_markup=stats_menu(), parse_mode="HTML")

    await cb.answer()


@router.callback_query(F.data.startswith("ch:"))
async def cb_channel(cb: CallbackQuery):
    data = cb.data.split(":")[1]
    if data == "join":
        await cb.answer("⏳ در حال عضویت...")
        asyncio.create_task(_join_all_task(cb))
    elif data == "check":
        await cb.answer("⏳ در حال بررسی...")
        asyncio.create_task(_check_join_task(cb))
    elif data == "info":
        await cb.answer(f"📢 {Config.TARGET_CHANNEL_USERNAME}", show_alert=True)
    else:
        await cb.answer()


async def _join_all_task(cb: CallbackQuery):
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


async def _check_join_task(cb: CallbackQuery):
    try:
        from core.engine import make_client
        accounts = db.get_all_accounts()
        joined = 0
        for a in accounts:
            try:
                ss = db.get_session(a["phone"])
                c  = make_client(ss, phone=a["phone"])
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


@router.callback_query(F.data.startswith("set:"))
async def cb_settings(cb: CallbackQuery):
    data = cb.data.split(":")[1]
    msgs = {
        "shift":    "⏱️ طول شیفت: ۲۵-۴۵ دقیقه تصادفی",
        "active":   f"👥 تعداد فعال: {Config.SHIFT_SIZE}",
        "guardian": "🛡️ نگهبان هر ۶۰ ثانیه چک می‌کنه",
        "backup":   "💾 هر ۱ ساعت بکاپ ساخته می‌شه",
        "warp":     "📊 وضعیت WARP در آمار پیشرفته",
    }
    await cb.answer(msgs.get(data, ""), show_alert=True)


@router.callback_query(F.data.startswith("cfm:"))
async def cb_confirm(cb: CallbackQuery):
    d      = cb.data.split(":")
    action = d[2] if len(d) > 2 else ""
    yes    = d[1] == "yes"
    await cb.answer(f"{'✅' if yes else '❌'} {action}")


# ═══ FSM: افزودن اکانت ═══
async def _join_channel(client):
    try:
        target = Config.TARGET_CHANNEL_USERNAME or Config.TARGET_CHANNEL_ID
        if not target: return
        entity = await client.get_entity(target)
        try:
            from telethon.tl.functions.channels import JoinChannelRequest
            await client(JoinChannelRequest(entity))
        except Exception as e:
            if "already" not in str(e).lower():
                db.debug_log("handlers", "join", "WARN", str(type(e).__name__))
    except Exception:
        pass


@router.message(StateFilter(AddAccount.waiting_phone))
async def add_phone(msg: Message, state: FSMContext):
    if not await guard(msg): return
    phone = msg.text.strip()
    if not phone.startswith("+") or len(phone) < 10:
        await msg.answer("❌ فرمت اشتباه. مثال: <code>+989123456789</code>", parse_mode="HTML")
        return
    if db.get_account(phone):
        await msg.answer("⚠️ این شماره قبلاً ثبت شده.")
        await state.clear()
        return

    await msg.answer(f"📱 <code>{phone}</code>\n⏳ در حال ارسال کد...", parse_mode="HTML")
    c = None
    try:
        c = TelegramClient(StringSession(), Config.API_ID, Config.API_HASH)
        await asyncio.wait_for(c.connect(), timeout=20)
        sent = await asyncio.wait_for(c.send_code_request(phone), timeout=25)
        _pending[msg.from_user.id] = c
        await state.update_data(phone=phone, phone_code_hash=sent.phone_code_hash)
        await state.set_state(AddAccount.waiting_code)
        await msg.answer("✉️ <b>کد ارسال شد</b>\n\nکد رو با اعداد انگلیسی وارد کن:", parse_mode="HTML")
    except asyncio.TimeoutError:
        await msg.answer("❌ <b>Timeout</b>\nسرور تلگرام پاسخ نداد.", parse_mode="HTML")
        if c:
            try: await c.disconnect()
            except Exception: pass
        await state.clear()
    except Exception as e:
        err  = str(e)
        hint = ""
        if "PHONE_NUMBER_INVALID" in err:  hint = "\n📌 شماره اشتباه"
        elif "PHONE_NUMBER_BANNED" in err: hint = "\n📌 شماره بن شده"
        elif "FLOOD" in err.upper():       hint = "\n📌 ۵ دقیقه صبر کن"
        await msg.answer(f"❌ <b>خطا</b>: <code>{err[:150]}</code>{hint}", parse_mode="HTML")
        if c:
            try: await c.disconnect()
            except Exception: pass
        _pending.pop(msg.from_user.id, None)
        await state.clear()


@router.message(StateFilter(AddAccount.waiting_code))
async def add_code(msg: Message, state: FSMContext):
    if not await guard(msg): return
    code = msg.text.strip().replace("-", "").replace(" ", "")
    data = await state.get_data()
    phone = data["phone"]
    c = _pending.get(msg.from_user.id)
    if not c:
        await msg.answer("❌ کلاینت پیدا نشد. دوباره شروع کن.")
        await state.clear()
        return
    try:
        await c.sign_in(phone, code, phone_code_hash=data["phone_code_hash"])
        ss  = c.session.save()
        me  = await c.get_me()
        await _join_channel(c)
        await c.disconnect()
        _pending.pop(msg.from_user.id, None)
        acc_id = db.add_account(phone, ss)
        await msg.answer(
            f"✅ <b>اکانت اضافه شد!</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 نام: <b>{me.first_name}</b>\n"
            f"🆔 یوزرنیم: @{me.username or 'ندارد'}\n"
            f"🎫 شناسه: <code>{acc_id}</code>",
            reply_markup=main_menu(), parse_mode="HTML"
        )
        await state.clear()
    except SessionPasswordNeededError:
        await msg.answer("🔐 <b>رمز دو مرحله‌ای</b>\n\nرمز رو وارد کن:", parse_mode="HTML")
        await state.set_state(AddAccount.waiting_password)
    except Exception as e:
        await msg.answer(f"❌ خطا: <code>{e}</code>", parse_mode="HTML")
        try: await c.disconnect()
        except Exception: pass
        _pending.pop(msg.from_user.id, None)
        await state.clear()


@router.message(StateFilter(AddAccount.waiting_password))
async def add_password(msg: Message, state: FSMContext):
    if not await guard(msg): return
    pwd   = msg.text.strip()
    data  = await state.get_data()
    phone = data["phone"]
    c = _pending.get(msg.from_user.id)
    if not c:
        await msg.answer("❌ کلاینت پیدا نشد.")
        await state.clear()
        return
    try:
        # روش صحیح 2FA در telethon
        pwd_info = await c(GetPasswordRequest())
        pwd_check = compute_check(pwd_info, pwd)
        await c(functions.auth.CheckPasswordRequest(password=pwd_check))

        ss = c.session.save()
        me = await c.get_me()
        await _join_channel(c)
        await c.disconnect()
        _pending.pop(msg.from_user.id, None)
        acc_id = db.add_account(phone, ss)
        await msg.answer(
            f"✅ <b>اکانت با 2FA اضافه شد!</b>\n\n👤 {me.first_name}\n🎫 {acc_id}",
            reply_markup=main_menu(), parse_mode="HTML"
        )
        await state.clear()
    except Exception as e:
        err = str(e)
        hint = ""
        if "PASSWORD_HASH_INVALID" in err or "invalid" in err.lower():
            hint = "\n📌 رمز اشتباهه، دوباره وارد کن:"
            await msg.answer(f"❌ رمز اشتباه است.{hint}", parse_mode="HTML")
            return  # state رو نگه می‌داریم تا دوباره وارد کنه
        await msg.answer(f"❌ خطا: <code>{err}</code>", parse_mode="HTML")
        try: await c.disconnect()
        except Exception: pass
        _pending.pop(msg.from_user.id, None)
        await state.clear()


@router.callback_query(F.data == "add:cancel")
async def add_cancel(cb: CallbackQuery, state: FSMContext):
    c = _pending.pop(cb.from_user.id, None)
    if c:
        try: await c.disconnect()
        except Exception: pass
    await state.clear()
    await cb.message.edit_text("❌ لغو شد.", reply_markup=accounts_menu())
    await cb.answer("لغو")


def register_handlers(dp):
    """ثبت همه روترها روی Dispatcher"""
    from bot.antilock_handler import router as antilock_router
    dp.include_router(router)
    dp.include_router(antilock_router)
