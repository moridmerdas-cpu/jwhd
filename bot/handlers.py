"""هندلرهای کامل ربات — aiogram 3"""
import asyncio
import sys
from datetime import datetime
from pathlib import Path

from aiogram import types, Router, F, Bot
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import Config
from models import database as db
from bot.keyboards import (
    main_menu, status_menu, accounts_menu, accounts_list_kb,
    stats_menu, settings_menu, group_menu, confirm_menu,
    cancel_menu, view_toggle_menu, shift_select_menu, shift_timing_menu,
    use_members_menu, robot_member_menu,
)
from bot.states import AddAccount, SetShiftTiming, SetGroup, UseMembers

router = Router()

_pending: dict        = {}
_pending_clients      = _pending


# ─────────────────────────────────────────────────────────
# helpers
# ─────────────────────────────────────────────────────────
def is_admin(uid: int) -> bool:
    return uid in Config.ADMIN_IDS


async def guard(msg: types.Message) -> bool:
    if not is_admin(msg.from_user.id):
        await msg.answer("⛔ دسترسی ندارید.")
        return False
    return True


guard_admin = guard


_FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def _normalize_phone(raw: str) -> str | None:
    """ارقام فارسی/عربی، فاصله، خط تیره و پیشوندهای 09xx / 98xx / 00xx رو به +E.164 تبدیل می‌کنه."""
    s = raw.translate(_FA_DIGITS)
    s = "".join(ch for ch in s if ch.isdigit() or ch == "+")
    if s.startswith("00"):
        s = "+" + s[2:]
    elif s.startswith("09") and len(s) == 11:
        s = "+98" + s[1:]
    elif s.startswith("98") and len(s) == 12:
        s = "+" + s
    elif not s.startswith("+") and s.isdigit() and len(s) >= 10:
        s = "+" + s
    digits = s[1:]
    if not s.startswith("+") or not digits.isdigit() or not (10 <= len(digits) <= 15):
        return None
    return s


def _get_group_id():
    """یوزرنیم (str) یا آیدی عددی (int) یا 0"""
    return db.get_target_group()


# ─────────────────────────────────────────────────────────
# /start  /help  /admin
# ─────────────────────────────────────────────────────────
@router.message(Command("start"))
async def cmd_start(msg: types.Message):
    if not await guard(msg): return
    total    = len(db.get_all_accounts())
    group_id = _get_group_id()
    mn       = int(db.get_setting("shift_min_sec", Config.SHIFT_MIN_SEC)) // 60
    mx       = int(db.get_setting("shift_max_sec", Config.SHIFT_MAX_SEC)) // 60
    await msg.answer(
        f"🌟 <b>{Config.BOT_NAME}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👋 سلام!\n"
        f"🤖 این ربات سین‌زن حرفه‌ای شماست\n\n"
        f"📊 وضعیت سریع:\n"
        f"  👥 اکانت: <b>{total}</b>\n"
        f"  🎯 گروه: <code>{db.fmt_group(group_id)}</code>\n"
        f"  ⏰ چرخش: هر {mn}-{mx} دقیقه\n\n"
        f"👇 از منو انتخاب کنید:",
        reply_markup=main_menu(),
        parse_mode="HTML",
    )


@router.message(Command("help"))
@router.message(F.text.startswith("❓"))
async def cmd_help(msg: types.Message):
    if not await guard(msg): return
    await msg.answer(
        "📖 <b>راهنمای استفاده</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "➕ <b>افزودن اکانت</b>: شماره رو وارد کن، کد رو بده\n"
        "📊 <b>وضعیت زنده</b>: تعداد آنلاین/Flood/خطا\n"
        "👥 <b>مدیریت اکانت‌ها</b>: لیست، افزودن، چرخش، حذف\n"
        "📈 <b>آمار پیشرفته</b>: آمار ۲۴ ساعت، نمودار موفقیت\n"
        "🔄 <b>چرخش دستی</b>: تعویض فوری شیفت\n"
        "🎯 <b>گروه هدف</b>: تنظیم گروه، عضویت، چک\n"
        "⚙️ <b>تنظیمات</b>: بازه شیفت، شیفت فعال، نگهبان\n\n"
        "💡 <b>نکات</b>:\n"
        "• بین هر اکانت ۳-۵ دقیقه صبر کن\n"
        "• اگه Flood دیدی، ۱۰ دقیقه صبر کن",
        reply_markup=main_menu(),
        parse_mode="HTML",
    )


@router.message(Command("admin"))
async def cmd_admin(msg: types.Message):
    if not await guard(msg): return
    await msg.answer("🔧 <b>پنل ادمین</b>\n\nهمه دسترسی‌ها فعاله.", parse_mode="HTML")


# ─────────────────────────────────────────────────────────
# وضعیت زنده
# ─────────────────────────────────────────────────────────
def _status_text() -> str:
    counts = db.count_by_status()
    total  = len(db.get_all_accounts())
    online = counts.get("online", 0)
    flood  = counts.get("flood",  0)
    err    = counts.get("error",  0)
    idle   = counts.get("idle",   0)

    def bar(n, mx=total):
        if mx == 0: return "▱" * 10
        return "▰" * int(n / mx * 10) + "▱" * (10 - int(n / mx * 10))

    now = datetime.now().strftime("%H:%M:%S")
    return (
        f"📊 <b>وضعیت زنده</b>  <code>{now}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🟢 آنلاین  {bar(online)}  <b>{online}</b>\n"
        f"💤 استراحت  {bar(idle)}  <b>{idle}</b>\n"
        f"🟡 Flood  {bar(flood)}  <b>{flood}</b>\n"
        f"🔴 خطا  {bar(err)}  <b>{err}</b>\n\n"
        f"📊 کل: <b>{total}</b> اکانت"
    )


@router.message(F.text.startswith("📊"))
async def show_status(msg: types.Message):
    if not await guard(msg): return
    await msg.answer(_status_text(), reply_markup=status_menu(), parse_mode="HTML")


# ─────────────────────────────────────────────────────────
# کنترل ویو
# ─────────────────────────────────────────────────────────
@router.message(F.text.startswith("🎬"))
async def show_view_toggle(msg: types.Message):
    if not await guard(msg): return
    from core.listener import is_view_paused
    paused     = is_view_paused()
    status_txt = "🔴 متوقف" if paused else "🟢 فعال"
    await msg.answer(
        f"🎬 <b>کنترل ویو زدن</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"وضعیت فعلی: <b>{status_txt}</b>\n",
        reply_markup=view_toggle_menu(paused),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("view:"))
async def cb_view_toggle(cb: types.CallbackQuery):
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

    paused     = is_view_paused()
    status_txt = "🔴 متوقف" if paused else "🟢 فعال"
    try:
        await cb.message.edit_text(
            f"🎬 <b>کنترل ویو زدن</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"وضعیت فعلی: <b>{status_txt}</b>\n",
            reply_markup=view_toggle_menu(paused),
            parse_mode="HTML",
        )
    except Exception:
        pass


# ─────────────────────────────────────────────────────────
# مدیریت اکانت‌ها
# ─────────────────────────────────────────────────────────
@router.message(F.text.startswith("👥"))
async def show_accounts(msg: types.Message):
    if not await guard(msg): return
    total  = len(db.get_all_accounts())
    online = db.count_by_status().get("online", 0)
    await msg.answer(
        f"👥 <b>مدیریت اکانت‌ها</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 تعداد: <b>{total}</b>\n"
        f"🟢 آنلاین: <b>{online}</b>\n\n"
        f"👇 گزینه مورد نظر:",
        reply_markup=accounts_menu(),
        parse_mode="HTML",
    )


# ─────────────────────────────────────────────────────────
# آمار
# ─────────────────────────────────────────────────────────
@router.message(F.text.startswith("📈"))
async def show_stats(msg: types.Message):
    if not await guard(msg): return
    await msg.answer(
        "📈 <b>آمار پیشرفته</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n👇 گزینه مورد نظر:",
        reply_markup=stats_menu(), parse_mode="HTML",
    )


# ─────────────────────────────────────────────────────────
# 🎯 گروه هدف
# ─────────────────────────────────────────────────────────
@router.message(F.text.startswith("🎯"))
async def show_group(msg: types.Message):
    if not await guard(msg): return
    group_id = _get_group_id()
    await msg.answer(
        f"🎯 <b>گروه هدف</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🆔 آیدی: <code>{db.fmt_group(group_id)}</code>\n\n"
        f"👇 گزینه مورد نظر:",
        reply_markup=group_menu(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "grp:set")
async def cb_group_set(cb: types.CallbackQuery, state: FSMContext):
    await cb.message.edit_text(
        "🎯 <b>تنظیم گروه هدف</b>\n\n"
        "یوزرنیم یا لینک گروه رو بفرست (پیشنهادی):\n"
        "<code>@mygroup</code>\n"
        "<code>https://t.me/mygroup</code>\n\n"
        "یا آیدی عددی:\n"
        "<code>-1001234567890</code>\n\n"
        "💡 فقط گروه/کانال <b>عمومی</b> یوزرنیم داره. لینک دعوت خصوصی (t.me/+...) پشتیبانی نمیشه.",
        reply_markup=cancel_menu(),
        parse_mode="HTML",
    )
    await state.set_state(SetGroup.waiting_id)
    await cb.answer()


@router.message(StateFilter(SetGroup.waiting_id))
async def set_group_id(msg: types.Message, state: FSMContext):
    if not await guard(msg): return
    raw = (msg.text or "").strip()
    ref = db.parse_group_ref(raw)
    if not ref:
        if "joinchat" in raw or "t.me/+" in raw:
            await msg.answer("❌ لینک دعوت خصوصی پشتیبانی نمیشه. یوزرنیم عمومی (<code>@mygroup</code>) یا آیدی عددی بفرست.",
                             parse_mode="HTML")
        else:
            await msg.answer("❌ فرمت اشتباه. مثال: <code>@mygroup</code> یا <code>https://t.me/mygroup</code> یا <code>-1001234567890</code>",
                             parse_mode="HTML")
        return

    db.set_setting("target_group_id", ref)
    text = (f"✅ گروه هدف تنظیم شد!\n🆔 <code>{db.fmt_group(ref)}</code>\n")
    if isinstance(ref, int) and raw.lstrip("-").isdigit() and int(raw) != ref:
        text += f"🔧 منفی/پیشوند اصلاح شد: <code>{raw}</code> ← <code>{ref}</code>\n"

    # اعتبارسنجی فوری با یکی از اکانت‌های وصل
    try:
        from core.pool import POOL
        from core.entity import resolve_group_entity
        from telethon.tl.types import User
        client = next((c for c in POOL.clients.values() if c.is_connected()), None)
        if client is None:
            text += "\n⚠️ هنوز اکانتی وصل نیست، تأیید نشد."
        else:
            ent = await resolve_group_entity(client, ref, timeout=15)
            if isinstance(ent, User):
                text += "\n⚠️ این یوزرنیم مال یه <b>کاربره</b>، نه گروه!"
            else:
                text += f"\n🔎 تأیید شد: <b>{getattr(ent, 'title', '?')}</b>"
                text += "\n💡 اکانت‌ها باید عضو گروه باشن: «عضویت همه اکانت‌ها» رو بزن."
    except Exception as e:
        text += f"\n⚠️ ذخیره شد ولی گروه پیدا نشد:\n<code>{str(e)[:150]}</code>"

    try:
        from core.listener import ensure_group_listener
        gl = await ensure_group_listener()
        gl._settings_ts = 0.0          # تنظیمات رو سریع دوباره بخونه
        text += "\n\n✅ لیسنر روشنه و گروه جدید رو برمی‌داره."
    except Exception as e:
        text += f"\n\n⚠️ لیسنر روشن نشد: <code>{str(e)[:100]}</code>"
    await msg.answer(text, reply_markup=main_menu(), parse_mode="HTML")
    await state.clear()


@router.callback_query(F.data.startswith("grp:"))
async def cb_group(cb: types.CallbackQuery):
    data     = cb.data.split(":")[1]
    group_id = _get_group_id()

    if data == "join":
        await cb.answer("⏳ در حال عضویت همه اکانت‌ها...")
        asyncio.create_task(_join_group_all_task(cb, group_id))

    elif data == "check":
        await cb.answer("⏳ در حال بررسی...")
        asyncio.create_task(_check_group_join_task(cb, group_id))

    elif data == "info":
        await cb.answer(f"🎯 گروه: {db.fmt_group(group_id)}", show_alert=True)

    elif data == "diag":
        await cb.answer()
        from core.listener import get_group_listener, ensure_group_listener
        gl = get_group_listener()
        if gl is None or not gl.is_running:
            if not group_id:
                await cb.message.answer("❌ گروه هدف تنظیم نشده.")
                return
            gl = await ensure_group_listener()
            await asyncio.sleep(3)
        await cb.message.answer(gl.diag_text(), parse_mode="HTML")

    elif data == "test":
        await cb.answer("⏳ تست روی آخرین پیام...")
        from core.listener import get_group_listener, ensure_group_listener
        gl = get_group_listener() or await ensure_group_listener()
        try:
            txt = await asyncio.wait_for(gl.test_round(), timeout=60)
        except Exception as e:
            txt = f"❌ تست شکست خورد:\n<code>{type(e).__name__}: {str(e)[:200]}</code>"
        await cb.message.answer(txt, parse_mode="HTML")

    elif data == "mode":
        from core.listener import get_group_listener, _MODES, _MODE_FA
        cur = db.get_setting("group_action", "both")
        nxt = _MODES[(_MODES.index(cur) + 1) % len(_MODES)] if cur in _MODES else "both"
        db.set_setting("group_action", nxt)
        gl = get_group_listener()
        if gl:
            gl.mode = nxt
        await cb.answer(f"⚙️ عملیات: {_MODE_FA[nxt]}", show_alert=True)

    try:
        await cb.answer()
    except Exception:
        pass


async def _group_members_task(cb: types.CallbackQuery, group_id, mode: str):
    """mode='join' عضو می‌کنه، mode='check' فقط عضویت رو چک می‌کنه. دلیل شکست‌ها رو گزارش می‌ده."""
    if not group_id:
        await cb.message.answer("❌ گروه هدف تنظیم نشده")
        return
    from collections import Counter
    from core.engine import make_client
    from core.entity import resolve_group_entity
    from telethon.tl.functions.channels import JoinChannelRequest, GetParticipantRequest
    try:
        accounts = db.get_all_accounts()
        ok, reasons = 0, Counter()
        for a in accounts:
            c = None
            try:
                c = make_client(db.get_session(a["phone"]), phone=a["phone"])
                await asyncio.wait_for(c.connect(), timeout=15)
                entity = await resolve_group_entity(c, group_id, timeout=15)
                if mode == "join":
                    await c(JoinChannelRequest(entity))
                else:
                    await c(GetParticipantRequest(channel=entity, participant="me"))
                ok += 1
                if mode == "join":
                    await asyncio.sleep(2)
            except Exception as e:
                msg_ = str(e).lower()
                if mode == "join" and ("already" in msg_ or "participant" in msg_):
                    ok += 1
                else:
                    reasons[f"{type(e).__name__}: {str(e)[:70]}"] += 1
            finally:
                if c is not None:
                    try:
                        await c.disconnect()
                    except Exception:
                        pass
        label = "عضو گروه شدن" if mode == "join" else "عضو گروه"
        text = f"✅ {ok}/{len(accounts)} اکانت {label}"
        for reason, n in reasons.most_common(4):
            text += f"\n🔴 {n}× <code>{reason}</code>"
        await cb.message.answer(text, parse_mode="HTML")
    except Exception as e:
        await cb.message.answer(f"❌ {e}")


async def _join_group_all_task(cb: types.CallbackQuery, group_id):
    await _group_members_task(cb, group_id, "join")


async def _check_group_join_task(cb: types.CallbackQuery, group_id):
    await _group_members_task(cb, group_id, "check")


# ─────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────
# 🤖 ربات ممبر گیر — عضویت و ترک لینک‌های ثابت
# ─────────────────────────────────────────────────────────

import re as _re

# لینک‌های هدف
_ROBOT_MEMBER_TARGETS = [
    "@freeads_org",
    "@cheallesh",
    "@speedy_member",
    "@linkdoney_ir",
    "https://t.me/+i5E_rPJfYj1hZWM0",
    "https://t.me/+itJEg-ElfM0xNzA0",
    "https://t.me/+SR2UvPj5M31jZjhk",
]

# کانالی که دکمه‌هاش رو می‌زنیم
_SPEEDY_CHANNEL = "@speedy_member"

# تعداد پیام‌هایی که دکمه «عضویت» و «دریافت الماس» روشون می‌زنیم
_SPEEDY_MSG_COUNT = 3


@router.callback_query(F.data == "mem:robot_member")
async def cb_robot_member_menu(cb: types.CallbackQuery):
    await cb.answer()
    total = len(db.get_all_accounts())
    targets_text = "\n".join(f"  • <code>{t}</code>" for t in _ROBOT_MEMBER_TARGETS)
    await cb.message.answer(
        f"🤖 <b>ربات ممبر گیر</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 تعداد اکانت‌های موجود: <b>{total}</b>\n\n"
        f"🎯 <b>لینک‌های هدف:</b>\n{targets_text}\n\n"
        f"یه عملیات انتخاب کن:",
        reply_markup=robot_member_menu(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "robmem:back")
async def cb_robmem_back(cb: types.CallbackQuery):
    await cb.answer()
    total = len(db.get_all_accounts())
    await cb.message.answer(
        f"🤖 <b>استفاده از ممبرها</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 تعداد اکانت‌های موجود: <b>{total}</b>\n\n"
        f"یکی از عملیات‌ها رو انتخاب کن:",
        reply_markup=use_members_menu(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "robmem:join")
async def cb_robmem_join(cb: types.CallbackQuery):
    await cb.answer("⏳ شروع عضویت...")
    await cb.message.answer(
        "⏳ <b>شروع عضویت در لینک‌های هدف...</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━",
        parse_mode="HTML",
    )
    asyncio.create_task(_robmem_join_task(cb))


@router.callback_query(F.data == "robmem:leave")
async def cb_robmem_leave(cb: types.CallbackQuery):
    await cb.answer("⏳ شروع ترک کردن...")
    await cb.message.answer(
        "⏳ <b>شروع ترک لینک‌های هدف...</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━",
        parse_mode="HTML",
    )
    asyncio.create_task(_robmem_leave_task(cb))


@router.callback_query(F.data == "robmem:speedy")
async def cb_robmem_speedy(cb: types.CallbackQuery):
    await cb.answer("⏳ شروع عملیات speedy...")
    await cb.message.answer(
        "💎 <b>speedy — عضویت و دریافت الماس</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "⏳ همه اکانت‌ها دارن دکمه‌های speedy_member رو می‌زنن...",
        parse_mode="HTML",
    )
    asyncio.create_task(_robmem_speedy_task(cb))


# ─── helpers ───

async def _robmem_join_one_target(client, target: str) -> str:
    """یه لینک رو join می‌کنه — برمی‌گردونه JOINED / ALREADY / ERR:..."""
    from telethon import functions as tl_funcs
    from telethon.errors import UserAlreadyParticipantError, FloodWaitError

    invite_match = _re.search(r"(?:joinchat/|\+)([A-Za-z0-9_\-]+)", target)
    try:
        if invite_match:
            hash_ = invite_match.group(1)
            await asyncio.wait_for(
                client(tl_funcs.messages.ImportChatInviteRequest(hash=hash_)),
                timeout=20,
            )
        else:
            username = target.lstrip("@").strip()
            if username.startswith("https://t.me/"):
                username = username.replace("https://t.me/", "").strip("/")
            entity = await asyncio.wait_for(client.get_entity(username), timeout=10)
            await asyncio.wait_for(
                client(tl_funcs.channels.JoinChannelRequest(channel=entity)),
                timeout=20,
            )
        return "JOINED"
    except UserAlreadyParticipantError:
        return "ALREADY"
    except FloodWaitError as e:
        await asyncio.sleep(min(e.seconds, 30))
        return f"FLOOD:{e.seconds}"
    except Exception as e:
        return f"ERR:{type(e).__name__}"


async def _robmem_leave_one_target(client, target: str) -> str:
    """از یه کانال/گروه leave می‌کنه — برمی‌گردونه LEFT / NOT_MEMBER / ERR:..."""
    from telethon import functions as tl_funcs
    from telethon.errors import UserNotParticipantError

    try:
        invite_match = _re.search(r"(?:joinchat/|\+)([A-Za-z0-9_\-]+)", target)
        if invite_match:
            # برای invite link باید اول entity رو بگیریم
            hash_ = invite_match.group(1)
            # سعی می‌کنیم channel رو از طریق hash پیدا کنیم
            try:
                result = await asyncio.wait_for(
                    client(tl_funcs.messages.CheckChatInviteRequest(hash=hash_)),
                    timeout=10,
                )
                # اگه already عضو بودیم chat رو داریم
                if hasattr(result, "chat"):
                    entity = result.chat
                else:
                    return "NOT_MEMBER"
            except Exception:
                return "NOT_MEMBER"
        else:
            username = target.lstrip("@").strip()
            if username.startswith("https://t.me/"):
                username = username.replace("https://t.me/", "").strip("/")
            entity = await asyncio.wait_for(client.get_entity(username), timeout=10)

        await asyncio.wait_for(
            client(tl_funcs.channels.LeaveChannelRequest(channel=entity)),
            timeout=20,
        )
        return "LEFT"
    except UserNotParticipantError:
        return "NOT_MEMBER"
    except Exception as e:
        return f"ERR:{type(e).__name__}"


async def _press_speedy_buttons(client) -> int:
    """
    توی کانال speedy_member آخرین _SPEEDY_MSG_COUNT پیام با دکمه رو پیدا می‌کنه.
    برای هر پیام:
      1. دکمه «عضویت» رو می‌زنه
      2. لینکی که توی پاسخ اومد رو join می‌کنه
      3. دکمه «دریافت الماس» رو می‌زنه
    برمی‌گردونه تعداد پیام‌هایی که پردازش شدن.
    """
    from telethon import functions as tl_funcs

    try:
        channel = await asyncio.wait_for(
            client.get_entity(_SPEEDY_CHANNEL), timeout=10
        )
    except Exception:
        return 0

    try:
        messages = await asyncio.wait_for(
            client.get_messages(channel, limit=30), timeout=15
        )
    except Exception:
        return 0

    button_msgs = [
        m for m in messages
        if m.reply_markup and hasattr(m.reply_markup, "rows")
    ][:_SPEEDY_MSG_COUNT]

    processed = 0
    for msg in button_msgs:
        try:
            rows = msg.reply_markup.rows
            all_btns = [btn for row in rows for btn in row.buttons]

            join_btn = None
            diamond_btn = None
            for btn in all_btns:
                txt = getattr(btn, "text", "") or ""
                if any(k in txt for k in ("عضویت", "عضو", "join", "Join")):
                    join_btn = btn
                if any(k in txt for k in ("الماس", "diamond", "دریافت", "Diamond")):
                    diamond_btn = btn

            # زدن دکمه عضویت
            if join_btn and getattr(join_btn, "data", None):
                try:
                    answer = await asyncio.wait_for(
                        client(tl_funcs.messages.GetBotCallbackAnswerRequest(
                            peer=channel,
                            msg_id=msg.id,
                            data=join_btn.data,
                        )),
                        timeout=15,
                    )
                    # اگه توی پاسخ لینک بود join کن
                    if answer and getattr(answer, "url", None):
                        url = answer.url
                        inv = _re.search(r"(?:joinchat/|\+)([A-Za-z0-9_\-]+)", url)
                        if inv:
                            try:
                                await asyncio.wait_for(
                                    client(tl_funcs.messages.ImportChatInviteRequest(
                                        hash=inv.group(1)
                                    )),
                                    timeout=20,
                                )
                            except Exception:
                                pass
                        elif "t.me/" in url:
                            uname = url.split("t.me/")[-1].strip("/")
                            try:
                                ent = await asyncio.wait_for(
                                    client.get_entity(uname), timeout=10
                                )
                                await asyncio.wait_for(
                                    client(tl_funcs.channels.JoinChannelRequest(channel=ent)),
                                    timeout=20,
                                )
                            except Exception:
                                pass
                    await asyncio.sleep(2)
                except Exception:
                    pass

            # زدن دکمه دریافت الماس
            if diamond_btn and getattr(diamond_btn, "data", None):
                try:
                    await asyncio.wait_for(
                        client(tl_funcs.messages.GetBotCallbackAnswerRequest(
                            peer=channel,
                            msg_id=msg.id,
                            data=diamond_btn.data,
                        )),
                        timeout=15,
                    )
                    await asyncio.sleep(2)
                except Exception:
                    pass

            processed += 1
        except Exception:
            continue

    return processed


# ─── Join Task ───

async def _robmem_join_task(cb: types.CallbackQuery):
    from core.engine import make_client

    accounts = db.get_all_accounts()
    total = len(accounts)
    ok = 0
    fail = 0

    status_msg = await cb.message.answer(
        f"🔄 <b>عضویت در حال اجرا</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 کل اکانت‌ها: <b>{total}</b>\n"
        f"⏳ در حال پردازش...",
        parse_mode="HTML",
    )

    sem = asyncio.Semaphore(3)

    async def process_account(acc):
        nonlocal ok, fail
        async with sem:
            phone = acc["phone"]
            client = make_client(db.get_session(phone), phone=phone)
            acc_ok = True
            try:
                await asyncio.wait_for(client.connect(), timeout=20)
                if not await client.is_user_authorized():
                    await client.disconnect()
                    fail += 1
                    return

                # عضویت در همه لینک‌ها
                for target in _ROBOT_MEMBER_TARGETS:
                    res = await _robmem_join_one_target(client, target)
                    if res.startswith("ERR"):
                        acc_ok = False
                    await asyncio.sleep(2)

                # زدن دکمه‌های speedy_member
                await _press_speedy_buttons(client)

                await client.disconnect()
                if acc_ok:
                    ok += 1
                else:
                    fail += 1

            except Exception:
                try:
                    await client.disconnect()
                except Exception:
                    pass
                fail += 1

            await asyncio.sleep(3)

    await asyncio.gather(*[process_account(a) for a in accounts])

    try:
        await status_msg.edit_text(
            f"✅ <b>عضویت تموم شد</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"✅ موفق: <b>{ok}</b>\n"
            f"❌ ناموفق: <b>{fail}</b>\n"
            f"👥 کل: <b>{total}</b>",
            parse_mode="HTML",
        )
    except Exception:
        pass


# ─── Leave Task ───

async def _robmem_leave_task(cb: types.CallbackQuery):
    from core.engine import make_client

    accounts = db.get_all_accounts()
    total = len(accounts)
    ok = 0
    fail = 0

    status_msg = await cb.message.answer(
        f"🔄 <b>ترک در حال اجرا</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 کل اکانت‌ها: <b>{total}</b>\n"
        f"⏳ در حال پردازش...",
        parse_mode="HTML",
    )

    sem = asyncio.Semaphore(5)

    async def leave_account(acc):
        nonlocal ok, fail
        async with sem:
            phone = acc["phone"]
            client = make_client(db.get_session(phone), phone=phone)
            acc_ok = True
            try:
                await asyncio.wait_for(client.connect(), timeout=20)
                if not await client.is_user_authorized():
                    await client.disconnect()
                    fail += 1
                    return

                for target in _ROBOT_MEMBER_TARGETS:
                    res = await _robmem_leave_one_target(client, target)
                    if res.startswith("ERR"):
                        acc_ok = False
                    await asyncio.sleep(1.5)

                await client.disconnect()
                if acc_ok:
                    ok += 1
                else:
                    fail += 1

            except Exception:
                try:
                    await client.disconnect()
                except Exception:
                    pass
                fail += 1

            await asyncio.sleep(2)

    await asyncio.gather(*[leave_account(a) for a in accounts])

    try:
        await status_msg.edit_text(
            f"✅ <b>ترک تموم شد</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"✅ موفق: <b>{ok}</b>\n"
            f"❌ ناموفق: <b>{fail}</b>\n"
            f"👥 کل: <b>{total}</b>",
            parse_mode="HTML",
        )
    except Exception:
        pass


# ─── Speedy Task ───

async def _robmem_speedy_task(cb: types.CallbackQuery):
    """همه اکانت‌ها رو می‌فرسته توی speedy_member تا دکمه عضویت و دریافت الماس رو بزنن"""
    from core.engine import make_client

    accounts = db.get_all_accounts()
    total = len(accounts)
    ok = 0
    fail = 0

    status_msg = await cb.message.answer(
        f"🔄 <b>speedy — در حال اجرا</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 کل اکانت‌ها: <b>{total}</b>\n"
        f"⏳ در حال پردازش...",
        parse_mode="HTML",
    )

    sem = asyncio.Semaphore(3)

    async def process_account(acc):
        nonlocal ok, fail
        async with sem:
            phone = acc["phone"]
            client = make_client(db.get_session(phone), phone=phone)
            try:
                await asyncio.wait_for(client.connect(), timeout=20)
                if not await client.is_user_authorized():
                    await client.disconnect()
                    fail += 1
                    return

                pressed = await _press_speedy_buttons(client)
                await client.disconnect()

                if pressed > 0:
                    ok += 1
                else:
                    fail += 1

            except Exception:
                try:
                    await client.disconnect()
                except Exception:
                    pass
                fail += 1

            await asyncio.sleep(3)

    await asyncio.gather(*[process_account(a) for a in accounts])

    try:
        await status_msg.edit_text(
            f"✅ <b>speedy — تموم شد</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"✅ موفق: <b>{ok}</b>\n"
            f"❌ ناموفق: <b>{fail}</b>\n"
            f"👥 کل: <b>{total}</b>",
            parse_mode="HTML",
        )
    except Exception:
        pass


# 🤖 استفاده از ممبرها
# ─────────────────────────────────────────────────────────

@router.message(F.text.startswith("🤖 استفاده از ممبرها"))
async def show_use_members(msg: types.Message):
    if not await guard(msg): return
    total = len(db.get_all_accounts())
    await msg.answer(
        f"🤖 <b>استفاده از ممبرها</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 تعداد اکانت‌های موجود: <b>{total}</b>\n\n"
        f"یکی از عملیات‌ها رو انتخاب کن:",
        reply_markup=use_members_menu(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("mem:"))
async def cb_use_members(cb: types.CallbackQuery, state: FSMContext):
    action = cb.data.split(":")[1]

    if action == "start_bot":
        await cb.answer()
        await cb.message.answer(
            "🚀 <b>استارت ربات</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "لینک دعوت ربات هدف رو بفرست:\n"
            "<code>https://t.me/botusername?start=xxx</code>\n"
            "یا یوزرنیم ربات:\n"
            "<code>@botusername</code>",
            reply_markup=cancel_menu(),
            parse_mode="HTML",
        )
        await state.set_state(UseMembers.waiting_start_bot_link)

    elif action == "join_group":
        await cb.answer()
        await cb.message.answer(
            "👥 <b>عضو شدن توی گروه</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "لینک یا آیدی گروه/کانال رو بفرست:\n"
            "<code>https://t.me/groupusername</code>\n"
            "یا\n"
            "<code>@groupusername</code>\n"
            "یا آیدی عددی:\n"
            "<code>-100xxxxxxxxxx</code>",
            reply_markup=cancel_menu(),
            parse_mode="HTML",
        )
        await state.set_state(UseMembers.waiting_join_group_link)

    try:
        await cb.answer()
    except Exception:
        pass


# ─── FSM: استارت ربات با همه اکانت‌ها ───

@router.message(StateFilter(UseMembers.waiting_start_bot_link))
async def mem_start_bot_link(msg: types.Message, state: FSMContext):
    if not await guard(msg): return
    raw = (msg.text or "").strip()
    if not raw:
        await msg.answer("❌ لینک خالیه. دوباره بفرست یا انصراف بزن.")
        return

    # normalize: extract username and start param if deep link
    # https://t.me/botname?start=xxx  or  t.me/botname  or  @botname
    import re
    username  = None
    start_param = None
    deep = re.match(r"(?:https?://)?t\.me/([A-Za-z0-9_]+)\?start=(.+)", raw)
    if deep:
        username    = deep.group(1)
        start_param = deep.group(2)
    else:
        plain = re.match(r"(?:https?://)?t\.me/([A-Za-z0-9_]+)", raw)
        if plain:
            username = plain.group(1)
        elif raw.startswith("@"):
            username = raw[1:]
        else:
            username = raw.lstrip("@")

    if not username:
        await msg.answer("❌ لینک معتبر نیست. دوباره بفرست.")
        return

    await state.clear()
    await msg.answer(
        f"⏳ <b>شروع استارت ربات</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🎯 ربات: <code>@{username}</code>\n"
        f"🔑 پارامتر: <code>{start_param or '—'}</code>\n\n"
        f"در حال اجرا...",
        parse_mode="HTML",
    )
    asyncio.create_task(_start_bot_all_task(msg, username, start_param))


async def _start_bot_all_task(msg: types.Message, username: str, start_param: str | None):
    """با همه اکانت‌ها یکی یکی /start می‌زنه روی ربات هدف با تاخیر."""
    from core.engine import make_client
    from telethon.tl.functions.messages import StartBotRequest
    import random

    accounts = db.get_all_accounts()
    if not accounts:
        await msg.answer("❌ هیچ اکانتی موجود نیست.")
        return

    ok = 0
    errors: list[str] = []
    delay_min, delay_max = 3, 7   # ثانیه

    progress_msg = await msg.answer(
        f"🚀 <b>استارت ربات در حال اجرا</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"⏳ 0 / {len(accounts)} اکانت پردازش شد...",
        parse_mode="HTML",
    )

    for idx, a in enumerate(accounts, 1):
        c = None
        try:
            c = make_client(db.get_session(a["phone"]), phone=a["phone"])
            await asyncio.wait_for(c.connect(), timeout=15)

            bot_entity = await asyncio.wait_for(c.get_entity(username), timeout=15)
            await asyncio.wait_for(
                c(StartBotRequest(
                    bot=bot_entity,
                    peer=bot_entity,
                    start_param=start_param or "",
                )),
                timeout=20,
            )
            ok += 1
        except Exception as e:
            err_str = f"{a['phone']}: {type(e).__name__}: {str(e)[:60]}"
            errors.append(err_str)
            db.debug_log("handlers", "start_bot_all", "WARN", err_str)
        finally:
            if c is not None:
                try:
                    await c.disconnect()
                except Exception:
                    pass

        # آپدیت پروگرس هر ۵ اکانت
        if idx % 5 == 0 or idx == len(accounts):
            try:
                await progress_msg.edit_text(
                    f"🚀 <b>استارت ربات در حال اجرا</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"✅ {ok} / {idx} موفق\n"
                    f"❌ {idx - ok} خطا",
                    parse_mode="HTML",
                )
            except Exception:
                pass

        # تاخیر بین اکانت‌ها (آخری نیازی نداره)
        if idx < len(accounts):
            await asyncio.sleep(random.uniform(delay_min, delay_max))

    # گزارش نهایی
    text = (
        f"✅ <b>استارت ربات تموم شد</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🎯 ربات: <code>@{username}</code>\n"
        f"✅ موفق: <b>{ok}</b> / {len(accounts)}\n"
        f"❌ خطا: <b>{len(accounts) - ok}</b>"
    )
    for e in errors[:5]:
        text += f"\n🔴 <code>{e}</code>"
    if len(errors) > 5:
        text += f"\n... و {len(errors) - 5} خطای دیگه"
    await msg.answer(text, reply_markup=main_menu(), parse_mode="HTML")


# ─── FSM: عضو شدن توی گروه دلخواه ───

@router.message(StateFilter(UseMembers.waiting_join_group_link))
async def mem_join_group_link(msg: types.Message, state: FSMContext):
    if not await guard(msg): return
    raw = (msg.text or "").strip()
    if not raw:
        await msg.answer("❌ لینک خالیه. دوباره بفرست یا انصراف بزن.")
        return

    import re
    group_target = None
    link_match = re.match(r"(?:https?://)?t\.me/(?:joinchat/|\+)?([A-Za-z0-9_+\-]+)", raw)
    if link_match:
        slug = link_match.group(1)
        # اگه hash دعوت‌نامه‌ست (joinchat) کل لینک رو نگه می‌داریم
        if re.match(r"[A-Za-z0-9_\-]{16,}", slug) and not slug.startswith("+"):
            group_target = raw   # لینک دعوت خصوصی — کامل لازمه
        else:
            group_target = slug.lstrip("+") if slug.startswith("+") else slug
    elif raw.startswith("@"):
        group_target = raw[1:]
    elif raw.lstrip("-").isdigit():
        group_target = int(raw)
    else:
        group_target = raw.lstrip("@")

    if not group_target:
        await msg.answer("❌ لینک معتبر نیست. دوباره بفرست.")
        return

    await state.clear()
    display = raw if isinstance(group_target, str) and raw.startswith("https") else f"<code>{group_target}</code>"
    await msg.answer(
        f"⏳ <b>شروع عضویت در گروه</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🎯 گروه: {display}\n\n"
        f"در حال اجرا...",
        parse_mode="HTML",
    )
    asyncio.create_task(_join_target_group_all_task(msg, group_target))


async def _join_target_group_all_task(msg: types.Message, group_target):
    """با همه اکانت‌ها یکی یکی توی گروه هدف عضو می‌شه با تاخیر."""
    from core.engine import make_client
    from core.entity import resolve_group_entity
    from telethon.tl.functions.channels import JoinChannelRequest
    from telethon.tl.functions.messages  import ImportChatInviteRequest
    import random

    accounts = db.get_all_accounts()
    if not accounts:
        await msg.answer("❌ هیچ اکانتی موجود نیست.")
        return

    ok = 0
    errors: list[str] = []
    delay_min, delay_max = 3, 8

    # تشخیص لینک دعوت خصوصی
    is_invite_link = isinstance(group_target, str) and "t.me" in str(group_target)

    # استخراج hash از لینک دعوت
    invite_hash = None
    if is_invite_link:
        import re
        m = re.search(r"(?:joinchat/|\+)([A-Za-z0-9_\-]+)", str(group_target))
        if m:
            invite_hash = m.group(1)

    progress_msg = await msg.answer(
        f"👥 <b>عضویت در گروه در حال اجرا</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"⏳ 0 / {len(accounts)} اکانت پردازش شد...",
        parse_mode="HTML",
    )

    for idx, a in enumerate(accounts, 1):
        c = None
        try:
            c = make_client(db.get_session(a["phone"]), phone=a["phone"])
            await asyncio.wait_for(c.connect(), timeout=15)

            if invite_hash:
                # لینک دعوت خصوصی
                await asyncio.wait_for(
                    c(ImportChatInviteRequest(invite_hash)),
                    timeout=20,
                )
            else:
                entity = await asyncio.wait_for(
                    resolve_group_entity(c, group_target, timeout=15),
                    timeout=20,
                )
                await asyncio.wait_for(
                    c(JoinChannelRequest(entity)),
                    timeout=20,
                )
            ok += 1
        except Exception as e:
            err_low = str(e).lower()
            if "already" in err_low or "participant" in err_low or "you have already" in err_low:
                ok += 1   # قبلاً عضو بوده
            else:
                err_str = f"{a['phone']}: {type(e).__name__}: {str(e)[:60]}"
                errors.append(err_str)
                db.debug_log("handlers", "join_target_group", "WARN", err_str)
        finally:
            if c is not None:
                try:
                    await c.disconnect()
                except Exception:
                    pass

        if idx % 5 == 0 or idx == len(accounts):
            try:
                await progress_msg.edit_text(
                    f"👥 <b>عضویت در گروه در حال اجرا</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"✅ {ok} / {idx} موفق\n"
                    f"❌ {idx - ok} خطا",
                    parse_mode="HTML",
                )
            except Exception:
                pass

        if idx < len(accounts):
            await asyncio.sleep(random.uniform(delay_min, delay_max))

    text = (
        f"✅ <b>عضویت تموم شد</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🎯 گروه: <code>{group_target}</code>\n"
        f"✅ موفق: <b>{ok}</b> / {len(accounts)}\n"
        f"❌ خطا: <b>{len(accounts) - ok}</b>"
    )
    for e in errors[:5]:
        text += f"\n🔴 <code>{e}</code>"
    if len(errors) > 5:
        text += f"\n... و {len(errors) - 5} خطای دیگه"
    await msg.answer(text, reply_markup=main_menu(), parse_mode="HTML")


# ─────────────────────────────────────────────────────────
# ⚙️ تنظیمات
# ─────────────────────────────────────────────────────────
@router.message(F.text.startswith("⚙️"))
async def show_settings(msg: types.Message):
    if not await guard(msg): return
    mn = int(db.get_setting("shift_min_sec", Config.SHIFT_MIN_SEC)) // 60
    mx = int(db.get_setting("shift_max_sec", Config.SHIFT_MAX_SEC)) // 60
    from core.pool import POOL
    active = POOL.active_shift
    await msg.answer(
        f"⚙️ <b>تنظیمات</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"⏱️ بازه شیفت: <b>{mn}-{mx} دقیقه</b>\n"
        f"🔢 شیفت فعال: <b>{active}</b>\n\n"
        f"👇 گزینه مورد نظر:",
        reply_markup=settings_menu(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("set:"))
async def cb_settings(cb: types.CallbackQuery, state: FSMContext):
    data = cb.data.split(":")[1]

    if data == "shift_timing":
        mn = int(db.get_setting("shift_min_sec", Config.SHIFT_MIN_SEC)) // 60
        mx = int(db.get_setting("shift_max_sec", Config.SHIFT_MAX_SEC)) // 60
        await cb.message.edit_text(
            f"⏱️ <b>بازه تایم شیفت</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"⏰ فعلی: <b>{mn}-{mx} دقیقه</b>\n\n"
            f"یه پیش‌فرض انتخاب کن یا دستی وارد کن:",
            reply_markup=shift_timing_menu(),
            parse_mode="HTML",
        )

    elif data == "shift_active":
        from core.pool import POOL
        active = POOL.active_shift
        active_label = "🌐 همه شیفت‌ها" if active == 0 else f"شیفت {active}"
        await cb.message.edit_text(
            f"🔢 <b>انتخاب شیفت فعال</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"شیفت فعلی: <b>{active_label}</b>\n"
            f"تعداد شیفت‌ها: <b>{POOL.num_shifts}</b>\n\n"
            f"👇 شیفت مورد نظر رو انتخاب کن:",
            reply_markup=shift_select_menu(active),
            parse_mode="HTML",
        )

    elif data == "guardian":
        await cb.answer("🛡️ نگهبان هر ۶۰ ثانیه چک می‌کنه", show_alert=True)

    elif data == "backup":
        try:
            from core.backup import create_backup
            f = create_backup()
            await cb.answer(f"✅ بکاپ ساخته شد ({f.stat().st_size//1024}KB)", show_alert=True)
        except Exception as e:
            await cb.answer(f"❌ خطا: {e}", show_alert=True)

    elif data == "num_shifts":
        from core.pool import POOL
        mn = int(db.get_setting("shift_min_sec", Config.SHIFT_MIN_SEC)) // 60
        mx = int(db.get_setting("shift_max_sec", Config.SHIFT_MAX_SEC)) // 60
        shift_lines = "\n".join(
            f"  شیفت {i}: <b>{len(POOL.shifts.get(i, []))}</b> اکانت"
            for i in range(1, POOL.num_shifts + 1)
        )
        await cb.message.edit_text(
            f"🔢 <b>تعداد شیفت‌ها</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📋 شیفت‌های فعال: <b>{POOL.num_shifts}</b>\n"
            f"⏱️ بازه چرخش: <b>{mn}-{mx} دقیقه</b>\n\n"
            f"{shift_lines}\n\n"
            f"💡 اکانت‌ها رو از منوی اکانت‌ها به شیفت‌های مختلف اختصاص بده.",
            reply_markup=_back_to_settings_kb(),
            parse_mode="HTML",
        )

    elif data == "viewguard":
        from core.view_guard import VIEW_GUARD, MAX_VIEWS_PER_DAY, MIN_GAP_SEC, MAX_GAP_SEC
        from bot.keyboards import viewguard_menu
        stats = VIEW_GUARD.stats()
        await cb.message.edit_text(
            f"🔒 <b>تنظیمات ضد لیمیت (ViewGuard)</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📊 ویوهای امروز (کل): <b>{stats['total_views_today']}</b>\n"
            f"🚫 اکانت‌های flood: <b>{stats['flooded_now']}</b>\n"
            f"💤 سهمیه تموم‌شده: <b>{stats['exhausted_today']}</b>\n\n"
            f"⚙️ تنظیمات فعلی:\n"
            f"  📅 سهمیه روزانه هر اکانت: <b>{MAX_VIEWS_PER_DAY}</b>\n"
            f"  ⏳ فاصله بین ویو: <b>{MIN_GAP_SEC:.0f}-{MAX_GAP_SEC:.0f} ثانیه</b>\n\n"
            f"👇 گزینه مورد نظر:",
            reply_markup=viewguard_menu(),
            parse_mode="HTML",
        )

    try:
        await cb.answer()
    except Exception:
        pass


def _back_to_settings_kb():
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b = InlineKeyboardBuilder()
    b.button(text="🔙 برگشت به تنظیمات", callback_data="menu:settings")
    return b.as_markup()


# تنظیم بازه شیفت — پیش‌فرض
@router.callback_query(F.data.startswith("stm:preset:"))
async def cb_shift_timing_preset(cb: types.CallbackQuery):
    _, _, mn_str, mx_str = cb.data.split(":")
    mn = int(mn_str) * 60
    mx = int(mx_str) * 60
    db.set_setting("shift_min_sec", mn)
    db.set_setting("shift_max_sec", mx)
    await cb.answer(f"✅ بازه تنظیم شد: {mn_str}-{mx_str} دقیقه", show_alert=True)
    try:
        await cb.message.edit_text(
            f"⏱️ <b>بازه شیفت</b>\n\n✅ تنظیم شد: <b>{mn_str}-{mx_str} دقیقه</b>\n\n"
            f"شیفت بعدی این بازه رو استفاده می‌کنه.",
            reply_markup=shift_timing_menu(),
            parse_mode="HTML",
        )
    except Exception:
        pass


# تنظیم بازه شیفت — دستی
@router.callback_query(F.data == "stm:custom")
async def cb_shift_timing_custom(cb: types.CallbackQuery, state: FSMContext):
    await cb.message.edit_text(
        "⏱️ <b>بازه دلخواه</b>\n\n"
        "دو عدد بفرست (دقیقه):\n"
        "<code>حداقل حداکثر</code>\n\n"
        "مثال: <code>20 60</code>",
        reply_markup=cancel_menu(),
        parse_mode="HTML",
    )
    await state.set_state(SetShiftTiming.waiting_range)
    await cb.answer()


@router.message(StateFilter(SetShiftTiming.waiting_range))
async def set_shift_timing(msg: types.Message, state: FSMContext):
    if not await guard(msg): return
    parts = msg.text.strip().split()
    if len(parts) != 2:
        await msg.answer("❌ فرمت اشتباه. مثال: <code>20 60</code>", parse_mode="HTML")
        return
    try:
        mn, mx = int(parts[0]), int(parts[1])
        if mn < 1 or mx < mn + 1:
            raise ValueError
    except ValueError:
        await msg.answer("❌ اعداد معتبر نیستن. حداقل باید کمتر از حداکثر باشه.", parse_mode="HTML")
        return
    db.set_setting("shift_min_sec", mn * 60)
    db.set_setting("shift_max_sec", mx * 60)
    await msg.answer(
        f"✅ بازه شیفت تنظیم شد!\n"
        f"⏱️ <b>{mn}-{mx} دقیقه</b>\n\n"
        f"شیفت بعدی این بازه رو استفاده می‌کنه.",
        reply_markup=main_menu(),
        parse_mode="HTML",
    )
    await state.clear()


# انتخاب شیفت فعال
@router.callback_query(F.data.startswith("shift:select:"))
async def cb_shift_select(cb: types.CallbackQuery):
    shift = int(cb.data.split(":")[2])
    from core.pool import POOL
    old = POOL.active_shift

    # پیام انتظار
    old_label = "همه شیفت‌ها" if old == 0 else f"شیفت {old}"
    new_label  = "همه شیفت‌ها" if shift == 0 else f"شیفت {shift}"
    await cb.answer(f"⏳ {old_label} → {new_label} | در حال اتصال اکانت‌ها...")

    db.set_setting("active_shift", shift)
    try:
        rep = await asyncio.wait_for(POOL.activate_shift(shift), timeout=120)
    except Exception as e:
        total = len(POOL.all_phones) if shift == 0 else len(POOL.shifts.get(shift, []))
        rep = {"total": total, "connected": 0,
               "errors": {"-": f"{type(e).__name__}: {e}"}}

    if shift == 0:
        # حالت همه شیفت‌ها — جزئیات هر شیفت رو نشون میده
        shift_detail = "\n".join(
            f"  شیفت {i}: {len(POOL.shifts.get(i,[]))} اکانت"
            for i in range(1, 5)
        )
        text = (
            f"🌐 <b>همه شیفت‌ها فعال شدن</b>\n\n"
            f"🟢 متصل: <b>{rep['connected']}/{rep['total']}</b>\n\n"
            f"{shift_detail}"
        )
    else:
        text = (
            f"🔢 <b>شیفت فعال</b>\n\n✅ شیفت <b>{shift}</b> فعال شد.\n"
            f"🟢 متصل: <b>{rep['connected']}/{rep['total']}</b>"
        )
        if rep["total"] == 0:
            text += "\n\n⚠️ این شیفت هیچ اکانتی نداره."

    for phone, err in list(rep["errors"].items())[:8]:
        text += f"\n🔴 <code>{phone}</code>\n    <code>{err[:110]}</code>"
    try:
        await cb.message.edit_text(text, reply_markup=shift_select_menu(shift), parse_mode="HTML")
    except Exception:
        pass


# ─────────────────────────────────────────────────────────
# چرخش دستی
# ─────────────────────────────────────────────────────────
@router.message(F.text.startswith("🔄"))
async def manual_rotate(msg: types.Message):
    if not await guard(msg): return
    try:
        from core.scheduler import get_scheduler_instance, _STATE
        s   = get_scheduler_instance()
        old = s._current_shift
        new = await s.rotate_now()
        res = _STATE.get("last_activate_result") or {}
        connected = res.get("connected", "?")
        total     = res.get("total", "?")
        await msg.answer(
            f"🔄 <b>چرخش انجام شد</b>\n\n"
            f"🅰️ شیفت قبلی: <b>{old}</b>\n"
            f"🅱️ شیفت جدید: <b>{new}</b>\n"
            f"🔌 متصل: <b>{connected}/{total}</b>\n"
            f"📊 کل چرخش‌های موفق: <b>{_STATE.get('total_swap_count', 0)}</b>",
            parse_mode="HTML",
        )
    except Exception as e:
        await msg.answer(f"❌ خطا: {e}")


# ─────────────────────────────────────────────────────────
# Callback: منوی اصلی
# ─────────────────────────────────────────────────────────
@router.callback_query(F.data == "menu:main")
async def cb_main_menu(cb: types.CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await cb.message.edit_text("👇 از منوی زیر انتخاب کنید:")
    except Exception:
        pass
    await cb.answer("✅ برگشت به منو")


# ─────────────────────────────────────────────────────────
# Callback: وضعیت
# ─────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("status:"))
async def cb_status(cb: types.CallbackQuery):
    data   = cb.data.split(":")[1]
    counts = db.count_by_status()
    if data == "refresh":
        await cb.message.edit_text(_status_text(), reply_markup=status_menu(), parse_mode="HTML")
        await cb.answer("🔄 بروزرسانی شد")
        return
    n     = len(db.get_all_accounts()) if data == "all" else counts.get(data, 0)
    emoji = {"online": "🟢", "idle": "💤", "error": "🔴", "flood": "🟡", "all": "📊"}.get(data, "❓")
    await cb.answer(f"{emoji} {n} اکانت", show_alert=True)


# ─────────────────────────────────────────────────────────
# Callback: مدیریت اکانت
# ─────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("acc:"))
async def cb_accounts(cb: types.CallbackQuery, state: FSMContext):
    d = cb.data.split(":", 2)
    action = d[1]

    if action == "list":
        page     = int(d[2]) if len(d) > 2 else 0
        accounts = db.get_all_accounts()
        if not accounts:
            await cb.message.edit_text("📋 هیچ اکانتی نیست.", reply_markup=accounts_menu())
        else:
            await cb.message.edit_text(
                f"📋 <b>{len(accounts)} اکانت</b>\nصفحه {page+1}",
                reply_markup=accounts_list_kb(accounts, page),
                parse_mode="HTML",
            )

    elif action == "add":
        await state.set_state(AddAccount.waiting_phone)
        await cb.answer("✅ شماره رو بفرست")
        await cb.message.answer(
            "➕ <b>افزودن اکانت جدید</b>\n\n"
            "شماره رو با فرمت بین‌المللی بفرست:\n"
            "<code>+989123456789</code>",
            reply_markup=cancel_menu(),
            parse_mode="HTML",
        )

    elif action == "rotate":
        from core.scheduler import get_scheduler_instance, _STATE
        s = get_scheduler_instance()
        await s.rotate_now()
        await cb.answer("🔄 چرخش انجام شد", show_alert=True)
        await cb.message.edit_text(_status_text(), reply_markup=status_menu(), parse_mode="HTML")

    elif action == "cleanup":
        from supabase import create_client
        sb = create_client(Config.SUPABASE_URL, Config.SUPABASE_KEY)
        res = sb.table("accounts").select("id", count="exact").eq("status", "flood").execute()
        n = res.count or 0
        sb.table("accounts").update({"status": "idle", "flood_until": None}).eq("status", "flood").execute()
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
        from supabase import create_client
        sb = create_client(Config.SUPABASE_URL, Config.SUPABASE_KEY)
        res = sb.table("accounts").select("*").eq("id", acc_id).limit(1).execute()
        row = res.data[0] if res and res.data else None
        if row:
            a    = row
            icon = {"online": "🟢", "flood": "🟡", "error": "🔴", "idle": "💤"}.get(a["status"], "⚪")
            text = (
                f"<b>📱 اکانت #{acc_id}</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"{icon} وضعیت: <b>{a['status']}</b>\n"
                f"🔢 شیفت: <b>{a['shift']}</b>\n"
                f"🌐 پورت: <code>{a.get('proxy_port') or '-'}</code>\n"
                f"📅 ساخته: {str(a['created_at'])[:16]}\n"
            )
            if a.get("last_error"):
                text += f"\n⚠️ خطا: <code>{a['last_error'][:100]}</code>"
            await cb.message.edit_text(text, parse_mode="HTML")

    elif action == "noop":
        pass

    try:
        await cb.answer()
    except Exception:
        pass


# ─────────────────────────────────────────────────────────
# Callback: آمار
# ─────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("stats:"))
async def cb_stats(cb: types.CallbackQuery):
    data = cb.data.split(":")[1]

    if data == "general":
        accounts = db.get_all_accounts()
        counts   = db.count_by_status()
        from core.pool import POOL
        _SHIFT_EMOJIS = ["1️⃣","2️⃣","3️⃣","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]
        active_lbl = "🌐 همه شیفت‌ها" if POOL.active_shift == 0 else f"شیفت {POOL.active_shift}"
        shift_lines = "\n".join(
            f"{_SHIFT_EMOJIS[i-1] if i <= len(_SHIFT_EMOJIS) else '🔢'} شیفت {i}: "
            f"<b>{sum(1 for a in accounts if str(a.get('shift','')) == str(i))}</b>"
            for i in range(1, POOL.num_shifts + 1)
        )
        await cb.message.edit_text(
            f"📊 <b>آمار کلی</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🔢 شیفت فعال: <b>{active_lbl}</b>\n"
            f"📋 تعداد شیفت‌ها: <b>{POOL.num_shifts}</b>\n"
            f"👥 کل اکانت: <b>{len(accounts)}</b>\n"
            f"🟢 آنلاین: <b>{counts.get('online', 0)}</b>\n"
            f"💤 استراحت: <b>{counts.get('idle', 0)}</b>\n"
            f"🟡 Flood: <b>{counts.get('flood', 0)}</b>\n"
            f"🔴 خطا: <b>{counts.get('error', 0)}</b>\n\n"
            f"{shift_lines}",
            reply_markup=stats_menu(), parse_mode="HTML",
        )

    elif data == "daily":
        msgs = db.count_debug_log_since("new_msg", hours=24)
        await cb.message.edit_text(
            f"📈 <b>آمار ۲۴ ساعت</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📨 پیام‌های جدید: <b>{msgs}</b>\n",
            reply_markup=stats_menu(), parse_mode="HTML",
        )

    elif data == "shift":
        from core.scheduler import get_scheduler_instance, _STATE
        from core.pool import POOL
        cur    = POOL.active_shift
        nxt_dt = _STATE.get("next_swap_at")
        nxt    = nxt_dt.strftime("%H:%M:%S") if nxt_dt else "?"
        last_iv     = _STATE.get("last_interval", 0)
        total_swaps = _STATE.get("total_swap_count", 0)
        auto_swaps  = _STATE.get("swap_count", 0)
        manual_swaps = _STATE.get("manual_swap_count", 0)
        last_swap_at = _STATE.get("last_swap_at") or "هنوز نشده"
        res         = _STATE.get("last_activate_result") or {}
        connected   = res.get("connected", "?")
        total_acc   = res.get("total", "?")
        act_at      = res.get("at", "?")
        mn = int(db.get_setting("shift_min_sec", Config.SHIFT_MIN_SEC)) // 60
        mx = int(db.get_setting("shift_max_sec", Config.SHIFT_MAX_SEC)) // 60
        await cb.message.edit_text(
            f"🔄 <b>وضعیت چرخه</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🟢 شیفت فعال: <b>{cur}</b>\n"
            f"⏰ swap بعدی: <b>{nxt}</b>\n"
            f"⏱️ آخرین بازه: <b>{last_iv}s</b>\n"
            f"📊 تنظیم فعلی: <b>{mn}-{mx} دقیقه</b>\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"✅ <b>چرخش‌های موفق</b>\n"
            f"  🔁 کل: <b>{total_swaps}</b>\n"
            f"  🤖 خودکار: <b>{auto_swaps}</b>\n"
            f"  🖐 دستی: <b>{manual_swaps}</b>\n"
            f"  🕐 آخرین چرخش: <b>{last_swap_at}</b>\n\n"
            f"🔌 <b>آخرین activate</b>: <b>{connected}/{total_acc}</b> متصل (ساعت {act_at})",
            reply_markup=stats_menu(), parse_mode="HTML",
        )

    elif data == "chart":
        rows = db.chart_reads_last_12h()
        text = "📉 <b>نمودار ۱۲ ساعت</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
        for r in rows:
            h   = r["h"]
            ok  = r["ok"] or 0
            bar = "▰" * min(ok, 20) + "▱" * max(0, 20 - min(ok, 20))
            text += f"<code>{h}:00</code> {bar} <b>{ok}</b>\n"
        await cb.message.edit_text(text, reply_markup=stats_menu(), parse_mode="HTML")

    await cb.answer()


# ─────────────────────────────────────────────────────────
# Callback: تایید
# ─────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("cfm:"))
async def cb_confirm(cb: types.CallbackQuery):
    d      = cb.data.split(":")
    action = d[2] if len(d) > 2 else ""
    yes    = d[1] == "yes"
    await cb.answer(f"{'✅' if yes else '❌'} {action}")


# ─────────────────────────────────────────────────────────
# FSM: افزودن اکانت
# ─────────────────────────────────────────────────────────
async def _join_group(client):
    group_id = _get_group_id()
    if not group_id:
        return
    try:
        from core.entity import resolve_group_entity
        entity = await resolve_group_entity(client, group_id, timeout=15)
        from telethon.tl.functions.channels import JoinChannelRequest
        await client(JoinChannelRequest(entity))
    except Exception as e:
        err = str(e).lower()
        if "already" not in err and "participant" not in err:
            db.debug_log("handlers", "join_group", "WARN", f"{type(e).__name__}: {str(e)[:100]}")


@router.message(F.text.in_({"➕ افزودن اکانت", "➕ افزودن", "➕ افزودن جدید"}))
async def add_account_start(msg: types.Message, state: FSMContext):
    if not await guard_admin(msg): return
    await state.set_state(AddAccount.waiting_phone)
    group_id = _get_group_id()
    await msg.answer(
        "➕ <b>افزودن اکانت جدید</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "شماره رو با فرمت بین‌المللی بفرست:\n"
        "<code>+989123456789</code>\n\n"
        f"💡 اکانت خودکار عضو گروه می‌شه: <code>{db.fmt_group(group_id)}</code>",
        reply_markup=cancel_menu(),
        parse_mode="HTML",
    )


@router.message(StateFilter(AddAccount.waiting_phone))
async def add_phone(msg: types.Message, state: FSMContext):
    if not await guard_admin(msg): return
    phone = _normalize_phone(msg.text or "")
    if not phone:
        await msg.answer("❌ فرمت اشتباه. مثال: <code>+989123456789</code>", parse_mode="HTML")
        return
    try:
        exists = db.get_account(phone)
    except Exception as e:
        db.debug_log("handlers", "add_phone", "ERROR", f"{type(e).__name__}: {e}")
        await msg.answer(f"❌ خطای دیتابیس: <code>{type(e).__name__}: {str(e)[:150]}</code>", parse_mode="HTML")
        return
    if exists:
        await msg.answer("⚠️ این شماره قبلاً ثبت شده.")
        await state.clear()
        return

    await msg.answer(f"📱 <code>{phone}</code>\n⏳ در حال ارسال کد...", parse_mode="HTML")
    c = None
    try:
        c    = TelegramClient(StringSession(), Config.API_ID, Config.API_HASH)
        await asyncio.wait_for(c.connect(), timeout=20)
        sent = await asyncio.wait_for(c.send_code_request(phone), timeout=25)
        _pending_clients[msg.from_user.id] = c
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
        _pending_clients.pop(msg.from_user.id, None)
        await state.clear()


@router.message(StateFilter(AddAccount.waiting_code))
async def add_code(msg: types.Message, state: FSMContext):
    if not await guard(msg): return
    code  = msg.text.strip().replace("-", "").replace(" ", "")
    data  = await state.get_data()
    phone = data["phone"]
    c     = _pending.get(msg.from_user.id)
    if not c:
        await msg.answer("❌ کلاینت پیدا نشد. دوباره شروع کن.")
        await state.clear()
        return
    try:
        await c.sign_in(phone, code, phone_code_hash=data["phone_code_hash"])
        ss   = c.session.save()
        me   = await c.get_me()
        await _join_group(c)
        await c.disconnect()
        _pending.pop(msg.from_user.id, None)
        acc_id = db.add_account(phone, ss)

        # اکانت جدید رو بلافاصله وارد pool کن (با کلاینت تازه، نه کلاینت قطع‌شده)
        pool_ok = False
        try:
            from core.pool import POOL
            pool_ok = await asyncio.wait_for(POOL.add_account_live(phone), timeout=40) is not None
        except Exception as _pe:
            db.debug_log("handlers", "pool_add", "WARN", f"{type(_pe).__name__}: {_pe}")

        await msg.answer(
            f"✅ <b>اکانت اضافه شد!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 نام: <b>{me.first_name}</b>\n"
            f"🆔 یوزرنیم: @{me.username or 'ندارد'}\n"
            f"🎫 شناسه: <code>{acc_id}</code>\n"
            f"👥 عضو گروه: ✅\n"
            f"🔌 اتصال به pool: {'✅' if pool_ok else '⚠️ بعداً خودکار وصل میشه'}",
            reply_markup=main_menu(),
            parse_mode="HTML",
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
async def add_password(msg: types.Message, state: FSMContext):
    if not await guard(msg): return
    pwd   = msg.text.strip()
    data  = await state.get_data()
    phone = data["phone"]
    c     = _pending.get(msg.from_user.id)
    if not c:
        await msg.answer("❌ کلاینت پیدا نشد.")
        await state.clear()
        return
    try:
        await c.sign_in(password=pwd)
        ss     = c.session.save()
        me     = await c.get_me()
        await _join_group(c)
        await c.disconnect()
        _pending.pop(msg.from_user.id, None)
        acc_id = db.add_account(phone, ss)
        await msg.answer(
            f"✅ <b>اکانت با 2FA اضافه شد!</b>\n\n"
            f"👤 {me.first_name}\n"
            f"🎫 {acc_id}",
            reply_markup=main_menu(),
            parse_mode="HTML",
        )
        await state.clear()
    except Exception as e:
        await msg.answer(f"❌ خطا: <code>{e}</code>", parse_mode="HTML")
        try: await c.disconnect()
        except Exception: pass
        _pending.pop(msg.from_user.id, None)
        await state.clear()


@router.callback_query(F.data == "add:cancel")
async def add_cancel(cb: types.CallbackQuery, state: FSMContext):
    c = _pending.pop(cb.from_user.id, None)
    if c:
        try: await c.disconnect()
        except Exception: pass
    await state.clear()
    await cb.message.edit_text("❌ لغو شد.", reply_markup=accounts_menu())
    await cb.answer("لغو")


# ─────────────────────────────────────────────────────────
# register
# ─────────────────────────────────────────────────────────
async def _on_error(event: types.ErrorEvent):
    exc = event.exception
    db.debug_log("handlers", "unhandled", "ERROR", f"{type(exc).__name__}: {exc}")
    upd = event.update
    chat = None
    if upd.message:
        chat = upd.message.chat.id
    elif upd.callback_query and upd.callback_query.message:
        chat = upd.callback_query.message.chat.id
    if chat:
        try:
            await upd.bot.send_message(
                chat, f"⚠️ <b>خطای داخلی</b>\n<code>{type(exc).__name__}: {str(exc)[:200]}</code>",
                parse_mode="HTML")
        except Exception:
            pass
    return True


# ─────────────────────────────────────────────────────────
# ViewGuard FSM states
# ─────────────────────────────────────────────────────────
from aiogram.fsm.state import State, StatesGroup

class _VGState(StatesGroup):
    waiting_daily_quota = State()
    waiting_gap         = State()


# ─────────────────────────────────────────────────────────
# Callback: menu:settings (برگشت به تنظیمات)
# ─────────────────────────────────────────────────────────
@router.callback_query(F.data == "menu:settings")
async def cb_back_settings(cb: types.CallbackQuery):
    from bot.keyboards import settings_menu
    from core.pool import POOL
    mn = int(db.get_setting("shift_min_sec", Config.SHIFT_MIN_SEC)) // 60
    mx = int(db.get_setting("shift_max_sec", Config.SHIFT_MAX_SEC)) // 60
    try:
        await cb.message.edit_text(
            f"⚙️ <b>تنظیمات</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"⏱️ بازه شیفت: <b>{mn}-{mx} دقیقه</b>\n"
            f"🔢 شیفت فعال: <b>{POOL.active_shift}</b>\n\n"
            f"👇 گزینه مورد نظر:",
            reply_markup=settings_menu(),
            parse_mode="HTML",
        )
    except Exception:
        pass
    await cb.answer()


# ─────────────────────────────────────────────────────────
# Callback: vg:* (ViewGuard)
# ─────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("vg:"))
async def cb_viewguard(cb: types.CallbackQuery, state: FSMContext):
    from core.view_guard import VIEW_GUARD, MAX_VIEWS_PER_DAY, MIN_GAP_SEC, MAX_GAP_SEC
    from bot.keyboards import viewguard_menu
    action = cb.data.split(":")[1]

    if action == "stats":
        stats = VIEW_GUARD.stats()
        pct   = int(stats["total_views_today"] / max(stats["total_accounts"] * MAX_VIEWS_PER_DAY, 1) * 100)
        bar   = "▰" * min(pct // 10, 10) + "▱" * max(0, 10 - pct // 10)
        await cb.answer(
            f"📊 ویوی امروز: {stats['total_views_today']}\n"
            f"{bar}\n"
            f"🚫 flood: {stats['flooded_now']} | 💤 تموم: {stats['exhausted_today']}",
            show_alert=True,
        )

    elif action == "reset":
        # ریست state همه اکانت‌ها
        from core.view_guard import _AccountState
        for st in VIEW_GUARD._state.values():
            st.views_today = 0
            st.day_key     = ""
        await cb.answer("✅ آمار ویو همه اکانت‌ها ریست شد", show_alert=True)
        # آپدیت متن
        stats = VIEW_GUARD.stats()
        try:
            await cb.message.edit_text(
                f"🔒 <b>تنظیمات ضد لیمیت (ViewGuard)</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📊 ویوهای امروز (کل): <b>0</b>\n"
                f"🚫 اکانت‌های flood: <b>{stats['flooded_now']}</b>\n"
                f"💤 سهمیه تموم‌شده: <b>0</b>\n\n"
                f"⚙️ تنظیمات فعلی:\n"
                f"  📅 سهمیه روزانه هر اکانت: <b>{MAX_VIEWS_PER_DAY}</b>\n"
                f"  ⏳ فاصله بین ویو: <b>{MIN_GAP_SEC:.0f}-{MAX_GAP_SEC:.0f} ثانیه</b>\n\n"
                f"👇 گزینه مورد نظر:",
                reply_markup=viewguard_menu(),
                parse_mode="HTML",
            )
        except Exception:
            pass

    elif action == "set_daily":
        await cb.message.edit_text(
            f"📅 <b>سهمیه روزانه ویو</b>\n\n"
            f"فعلی: <b>{MAX_VIEWS_PER_DAY}</b> ویو در روز برای هر اکانت\n\n"
            f"عدد جدید رو بفرست (مثال: <code>80</code>):",
            reply_markup=cancel_menu(),
            parse_mode="HTML",
        )
        await state.set_state(_VGState.waiting_daily_quota)
        await cb.answer()
        return

    elif action == "set_gap":
        from core.view_guard import MIN_GAP_SEC, MAX_GAP_SEC
        await cb.message.edit_text(
            f"⏳ <b>فاصله بین ویوها</b>\n\n"
            f"فعلی: <b>{MIN_GAP_SEC:.0f}-{MAX_GAP_SEC:.0f} ثانیه</b>\n\n"
            f"دو عدد بفرست (ثانیه): حداقل حداکثر\n"
            f"مثال: <code>8 25</code>",
            reply_markup=cancel_menu(),
            parse_mode="HTML",
        )
        await state.set_state(_VGState.waiting_gap)
        await cb.answer()
        return

    try:
        await cb.answer()
    except Exception:
        pass


@router.message(StateFilter(_VGState.waiting_daily_quota))
async def vg_set_daily(msg: types.Message, state: FSMContext):
    if not await guard(msg): return
    raw = (msg.text or "").strip().translate(_FA_DIGITS)
    if not raw.isdigit() or int(raw) < 1:
        await msg.answer("❌ عدد معتبر وارد کن (مثال: <code>80</code>)", parse_mode="HTML")
        return
    import core.view_guard as vg
    vg.MAX_VIEWS_PER_DAY = int(raw)
    db.set_setting("vg_max_views_per_day", int(raw))
    await msg.answer(
        f"✅ سهمیه روزانه تنظیم شد: <b>{raw} ویو</b> برای هر اکانت",
        reply_markup=main_menu(), parse_mode="HTML",
    )
    await state.clear()


@router.message(StateFilter(_VGState.waiting_gap))
async def vg_set_gap(msg: types.Message, state: FSMContext):
    if not await guard(msg): return
    parts = (msg.text or "").strip().translate(_FA_DIGITS).split()
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        await msg.answer("❌ فرمت اشتباه. مثال: <code>8 25</code>", parse_mode="HTML")
        return
    mn, mx = int(parts[0]), int(parts[1])
    if mn < 1 or mx <= mn:
        await msg.answer("❌ حداقل باید کمتر از حداکثر باشه.", parse_mode="HTML")
        return
    import core.view_guard as vg
    vg.MIN_GAP_SEC = float(mn)
    vg.MAX_GAP_SEC = float(mx)
    db.set_setting("vg_min_gap", mn)
    db.set_setting("vg_max_gap", mx)
    await msg.answer(
        f"✅ فاصله ویو تنظیم شد: <b>{mn}-{mx} ثانیه</b>",
        reply_markup=main_menu(), parse_mode="HTML",
    )
    await state.clear()


def register_handlers(dp):
    dp.include_router(router)
    dp.errors.register(_on_error)
