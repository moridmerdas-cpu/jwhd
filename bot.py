#!/usr/bin/env python3
"""
عضویت اجباریه سپر — ربات عمومی و رایگانِ جوین اجباری چندگروهی
نیازمندی‌ها: python-telegram-bot==22.8  (پایتون 3.10+)
دیتابیس: Supabase (Postgres)
نصب: pip install -r requirements.txt

معماری چندمستاجری:
- ربات رایگان و عمومی است؛ هر کسی می‌تواند آن را به گروه خودش اضافه کند.
- وقتی کسی ربات را در گروهی ادمین می‌کند، همان شخص «مالک آن گروه» ثبت می‌شود و
  فقط او (یا مالک اصلی ربات) می‌تواند از پیوی ربات، آیتم‌های جوین اجباری همان
  گروه، متن‌های هشدار/تاییدِ همان گروه و زمان حذف پیام هشدار را مدیریت کند.
- مالک اصلیِ کل ربات، آیدی عددی ثابت OWNER_ID است. هر آیتمی که مالک اصلی اضافه
  می‌کند «سراسری» است و به‌صورت خودکار در جوین اجباریِ همه‌ی گروه‌ها قرار می‌گیرد؛
  مالک اصلی هم‌چنین دسترسی مدیریت به تمام گروه‌ها را دارد (پشتیبانی/نظارت).
- بقیه‌ی کاربران (مالکان گروه‌ها) فقط می‌توانند آیتم‌های جوین اجباریِ گروه خودشان
  را تنظیم کنند؛ این آیتم‌ها فقط در همان یک گروه اعمال می‌شوند.

جدول‌های مورد نیاز در Supabase (SQL):

    create table if not exists groups (
        id bigint primary key,                 -- آیدی عددی گروه در تلگرام
        owner_id bigint,                        -- آیدی عددی کسی که ربات را ادمین گروه کرده
        title text,
        warn_text text,
        joined_text text,
        delete_seconds double precision not null default 5,
        created_at timestamptz not null default now()
    );

    create table if not exists items (
        id bigint generated always as identity primary key,
        group_id bigint references groups(id) on delete cascade,  -- NULL = سراسری (همه‌ی گروه‌ها)
        kind text not null default 'channel',   -- 'channel' | 'group' | 'bot'
        chat_id text not null,                  -- آیدی عددی کانال/گروه یا یوزرنیم ربات (بدون @)
        title text not null,
        invite_link text not null,
        created_at timestamptz not null default now()
    );

    create table if not exists bot_starts (
        bot_username text not null,
        user_id bigint not null,
        started_at timestamptz not null default now(),
        primary key (bot_username, user_id)
    );

نکته‌ی مهم درباره‌ی آیتم از نوع «ربات»:
دکمه‌ی ربات یک لینک مستقیم به t.me/BOT?start=... است. بررسی واقعی ممکن نیست؛
وقتی کاربر دکمه‌ی «بررسی عضویت» را می‌زند، ورود او به همه‌ی ربات‌های آن لیست تایید
و در جدول bot_starts ثبت می‌شود. نیازی به تغییر در ربات مقصد یا دیتابیس مشترک نیست.

مصرف اینترنت:
- ربات کاملاً وبهوکی است (بدون polling)، هر چک عضویت فقط یک درخواست کوچک JSON به
  API تلگرام است، نتیجه‌ها کش می‌شوند (کش گروه/آیتم/عضویت) تا در هجوم پیام هم
  درخواست تکراری زده نشود، و هیچ polling یا دانلود فایلی در کد وجود ندارد؛ برای
  یک ربات با چند گروه معمولی، مصرف ماهانه به‌مراتب کمتر از ۵ گیگابایت می‌ماند.
"""

import asyncio
import html
import logging
import os
import re
import secrets
import time
from datetime import datetime, timezone
from typing import Optional

from aiohttp import web

from supabase import create_client, Client, ClientOptions

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Chat,
    User,
)
from telegram.constants import ChatMemberStatus, ParseMode
from telegram.error import BadRequest, Conflict, Forbidden, NetworkError, RetryAfter, TelegramError, TimedOut
from telegram.request import HTTPXRequest
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ChatMemberHandler,
    ContextTypes,
    filters,
)

# ---------------------------------------------------------------------------
# تنظیمات ثابت
# ---------------------------------------------------------------------------

BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
BOT_DISPLAY_NAME = "عضویت اجباریه سپر"

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

# مالک اصلیِ کل ربات (ثابت). از طریق env می‌توان مالکان اصلیِ بیشتری هم اضافه کرد.
OWNER_ID = 8977934490
SUPER_OWNER_IDS = {OWNER_ID} | {
    int(value.strip())
    for value in os.environ.get("EXTRA_OWNER_IDS", "").split(",")
    if value.strip().lstrip("-").isdigit()
}

GLOBAL_SCOPE = "GLOBAL"

DEFAULT_WARN_TEXT = "<b>کاربر {mention}\nبرای ارسال پیام باید در موارد زیر عضو شوید:</b>"
DEFAULT_JOINED_TEXT = "<b>کاربر {mention} در همه‌ی موارد عضو شد ✅</b>"
DEFAULT_DELETE_SECONDS = 5.0

KIND_LABEL = {"channel": "کانال", "group": "گروه", "bot": "ربات"}
KIND_ICON = {"channel": "📢", "group": "👥", "bot": "🤖"}

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("forcejoin_bot")

# ---------------------------------------------------------------------------
# لایه دیتابیس (Supabase) — بلاک‌کننده را از event loop اصلی دور نگه می‌داریم
# ---------------------------------------------------------------------------
# تمام تماس‌های supabase-py سینک/بلاک‌کننده هستند؛ برای همین هر تماس با
# asyncio.to_thread در ترد جدا اجرا می‌شود تا event loop اصلی هیچ‌وقت قفل نشود
# (در حالت وبهوک یعنی پردازش آپدیت‌های دیگر هیچ‌وقت متوقف نمی‌شود).

DB_TIMEOUT_SECONDS = 10

supabase: Client = create_client(
    SUPABASE_URL,
    SUPABASE_KEY,
    options=ClientOptions(postgrest_client_timeout=DB_TIMEOUT_SECONDS),
)


def _safe_db(fn, default=None):
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        logger.error("خطای دیتابیس: %s", exc)
        return default


# کش کوتاه‌مدت: برای جلوگیری از رفت‌وبرگشت زیاد به Supabase در هجوم پیام (و در
# نتیجه مصرف کمتر اینترنت). با هر تغییر ادمین بلافاصله پاک می‌شود، پس TTL
# طولانی هیچ تاخیری در دیدنِ تغییرات ایجاد نمی‌کند.
CACHE_TTL_SECONDS = 90.0
_db_cache: dict = {}


def _cache_get(key: str):
    hit = _db_cache.get(key)
    if hit is not None and time.monotonic() - hit[0] < CACHE_TTL_SECONDS:
        return True, hit[1]
    return False, None


def _cache_put(key: str, value) -> None:
    _db_cache[key] = (time.monotonic(), value)


def _cache_clear() -> None:
    _db_cache.clear()
    _membership_cache.clear()


# ---------------------------------------------------------------------------
# گروه‌ها
# ---------------------------------------------------------------------------


async def get_group(group_id: int) -> Optional[dict]:
    hit, cached = _cache_get(f"group:{group_id}")
    if hit:
        return cached

    def _run():
        res = supabase.table("groups").select("*").eq("id", group_id).execute()
        value = res.data[0] if res.data else None
        _cache_put(f"group:{group_id}", value)
        return value

    return await asyncio.to_thread(_safe_db, _run, None)


async def list_groups_by_owner(owner_id: int) -> list:
    def _run():
        res = supabase.table("groups").select("*").eq("owner_id", owner_id).order("title").execute()
        return res.data or []

    return await asyncio.to_thread(_safe_db, _run, [])


async def list_all_groups() -> list:
    def _run():
        res = supabase.table("groups").select("*").order("title").execute()
        return res.data or []

    return await asyncio.to_thread(_safe_db, _run, [])


async def upsert_group_owner(group_id: int, owner_id: int, title: str) -> None:
    """وقتی ربات به گروهی اضافه/ادمین می‌شود صدا زده می‌شود؛ مالک همان لحظه را ثبت می‌کند."""

    def _run():
        existing = supabase.table("groups").select("id").eq("id", group_id).execute().data
        payload = {"id": group_id, "owner_id": owner_id, "title": title}
        if existing:
            supabase.table("groups").update(payload).eq("id", group_id).execute()
        else:
            supabase.table("groups").insert(payload).execute()

    await asyncio.to_thread(_safe_db, _run, None)
    _cache_clear()


async def set_group_field(group_id: int, field: str, value) -> Optional[str]:
    def _run():
        supabase.table("groups").update({field: value}).eq("id", group_id).execute()

    try:
        await asyncio.to_thread(_run)
        _cache_clear()
        return None
    except Exception as exc:  # noqa: BLE001
        logger.error("خطای دیتابیس هنگام ذخیره تنظیمات گروه: %s", exc)
        return str(exc)


async def get_warn_delete_seconds(group: Optional[dict]) -> float:
    if not group:
        return DEFAULT_DELETE_SECONDS
    try:
        return float(group.get("delete_seconds") or DEFAULT_DELETE_SECONDS)
    except (TypeError, ValueError):
        return DEFAULT_DELETE_SECONDS


def can_manage_scope(scope: str, user_id: int, group: Optional[dict]) -> bool:
    if user_id in SUPER_OWNER_IDS:
        return True
    if scope == GLOBAL_SCOPE:
        return False
    return bool(group) and group.get("owner_id") == user_id


# ---------------------------------------------------------------------------
# آیتم‌های جوین اجباری
# ---------------------------------------------------------------------------


def _scope_group_id(scope: str) -> Optional[int]:
    return None if scope == GLOBAL_SCOPE else int(scope)


async def add_item(scope: str, kind: str, chat_id: str, title: str, invite_link: str) -> Optional[str]:
    """در صورت موفقیت None برمی‌گرداند، در صورت خطا متن خطا را برمی‌گرداند."""
    group_id = _scope_group_id(scope)

    def _run():
        q = supabase.table("items").select("id").eq("chat_id", chat_id).eq("kind", kind)
        q = q.is_("group_id", "null") if group_id is None else q.eq("group_id", group_id)
        existing = q.execute().data
        payload = {"group_id": group_id, "kind": kind, "chat_id": chat_id, "title": title, "invite_link": invite_link}
        if existing:
            supabase.table("items").update(payload).eq("id", existing[0]["id"]).execute()
        else:
            supabase.table("items").insert(payload).execute()

    try:
        await asyncio.to_thread(_run)
        _cache_clear()
        return None
    except Exception as exc:  # noqa: BLE001
        logger.error("خطای دیتابیس هنگام افزودن آیتم: %s", exc)
        return str(exc)


async def update_item_link(item_id: int, invite_link: str) -> Optional[str]:
    def _run():
        supabase.table("items").update({"invite_link": invite_link}).eq("id", item_id).execute()

    try:
        await asyncio.to_thread(_run)
        _cache_clear()
        return None
    except Exception as exc:  # noqa: BLE001
        logger.error("خطای دیتابیس هنگام ویرایش لینک: %s", exc)
        return str(exc)


async def remove_item_by_id(item_id: int) -> bool:
    res = await asyncio.to_thread(
        _safe_db, lambda: supabase.table("items").delete().eq("id", item_id).execute()
    )
    _cache_clear()
    return bool(res and res.data)


async def list_scope_items(scope: str) -> list:
    """آیتم‌های تعریف‌شده در همین scope (برای پنل مدیریت)."""
    group_id = _scope_group_id(scope)
    key = f"scope_items:{scope}"
    hit, cached = _cache_get(key)
    if hit:
        return cached

    def _run():
        q = supabase.table("items").select("*").order("id")
        q = q.is_("group_id", "null") if group_id is None else q.eq("group_id", group_id)
        items = q.execute().data or []
        _cache_put(key, items)
        return items

    return await asyncio.to_thread(_safe_db, _run, [])


async def list_effective_items(group_id: int) -> list:
    """آیتم‌های سراسری + آیتم‌های همین گروه (برای اجرای جوین اجباری)."""
    key = f"effective_items:{group_id}"
    hit, cached = _cache_get(key)
    if hit:
        return cached

    def _run():
        res = (
            supabase.table("items")
            .select("*")
            .or_(f"group_id.is.null,group_id.eq.{group_id}")
            .order("id")
            .execute()
        )
        items = res.data or []
        _cache_put(key, items)
        return items

    return await asyncio.to_thread(_safe_db, _run, [])


async def get_item(item_id: int) -> Optional[dict]:
    def _run():
        res = supabase.table("items").select("*").eq("id", item_id).execute()
        return res.data[0] if res.data else None

    return await asyncio.to_thread(_safe_db, _run, None)


async def get_item_by_chat_id_in_scope(scope: str, chat_id: str) -> Optional[dict]:
    for it in await list_scope_items(scope):
        if str(it["chat_id"]) == str(chat_id):
            return it
    return None


async def has_started_bot(bot_username: str, user_id: int) -> bool:
    def _run():
        res = (
            supabase.table("bot_starts")
            .select("user_id")
            .eq("bot_username", bot_username.lower())
            .eq("user_id", user_id)
            .execute()
        )
        return bool(res.data)

    return await asyncio.to_thread(_safe_db, _run, False)


async def record_bot_start(bot_username: str, user_id: int) -> None:
    def _run():
        supabase.table("bot_starts").upsert(
            {"bot_username": bot_username.lower(), "user_id": user_id}
        ).execute()

    await asyncio.to_thread(_safe_db, _run)


# ---------------------------------------------------------------------------
# ابزارهای کمکی متن/کیبورد
# ---------------------------------------------------------------------------


def render_mention(user: User) -> str:
    """منشن HTML امن برای کاربر (اجباری در همه‌ی پیام‌ها)."""
    name = user.first_name or "کاربر"
    name = name.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f'<a href="tg://user?id={user.id}">{name}</a>'


def render_template(template: str, user: User) -> str:
    """جایگزینی متغیرها در متن سفارشی مالک گروه. متغیرها: {mention} و منشن_کاربر"""
    mention = render_mention(user)
    text = template.replace("{mention}", mention)
    text = text.replace("منشن_کاربر", mention)
    if mention not in text:
        text = f"{mention}\n{text}"
    return text


def build_items_list_text(items: list) -> str:
    """لیست خودکار موارد باقی‌مانده؛ داخل نقل قول (blockquote) چاپ می‌شود."""
    if not items:
        return ""
    lines = []
    for it in items:
        label = KIND_LABEL.get(it.get("kind", "channel"), "کانال")
        lines.append(f"{label}: {html.escape(it['title'])}")
    return "<blockquote>" + "\n".join(lines) + "</blockquote>"


async def build_full_warn_text(group: Optional[dict], user: User, items: list, use_default: bool = False) -> str:
    intro_template = DEFAULT_WARN_TEXT
    if not use_default and group and group.get("warn_text"):
        intro_template = group["warn_text"]
    intro = render_template(intro_template, user)
    items_text = build_items_list_text(items)
    if items_text:
        return f"{intro}\n\n{items_text}"
    return intro


def build_items_keyboard(items: list, user_id: int) -> InlineKeyboardMarkup:
    rows = []
    for it in items:
        icon = KIND_ICON.get(it.get("kind", "channel"), "📢")
        rows.append([InlineKeyboardButton(text=f"{icon} {it['title']}", url=it["invite_link"])])
    rows.append([InlineKeyboardButton("🔄 بررسی عضویت", callback_data=f"check_membership_{user_id}")])
    return InlineKeyboardMarkup(rows)


# ---------------------------------------------------------------------------
# بررسی عضویت
# ---------------------------------------------------------------------------


async def _check_single_item(bot, item: dict, user_id: int) -> bool:
    kind = item.get("kind", "channel")
    try:
        if kind == "bot":
            return await has_started_bot(item["chat_id"], user_id)
        member = await bot.get_chat_member(chat_id=item["chat_id"], user_id=user_id)
        return member.status in (
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
        )
    except (BadRequest, Forbidden) as exc:
        logger.warning("خطا در بررسی عضویت %s (%s): %s", item.get("title"), item.get("chat_id"), exc)
        return False
    except (TimedOut, NetworkError) as exc:
        logger.warning("تایم‌اوت شبکه هنگام بررسی %s: %s", item.get("title"), exc)
        return False


async def get_missing_items(bot, user_id: int, items: list) -> list:
    """آیتم‌هایی که کاربر هنوز در آن‌ها عضو نیست (بررسی موازی)."""
    if not items:
        return []
    results = await asyncio.gather(*[_check_single_item(bot, it, user_id) for it in items])
    return [it for it, ok in zip(items, results) if not ok]


MEMBERSHIP_OK_TTL_SECONDS = 180.0   # کاربری که همه‌چیز را کامل دارد: ۳ دقیقه دوباره چک نمی‌شود
MEMBERSHIP_MISS_TTL_SECONDS = 8.0   # کاربر ناقص: فقط برای هجوم پیام‌های هم‌زمان کش می‌شود
# کلید: (group_chat_id, user_id)
_membership_cache: dict = {}
_membership_inflight: dict = {}


def store_membership(group_chat_id: int, user_id: int, missing: list) -> None:
    key = (group_chat_id, user_id)
    if len(_membership_cache) > 8000:
        _membership_cache.clear()
    _membership_cache[key] = (time.monotonic(), {it["id"] for it in missing})


async def get_missing_items_fast(bot, group_chat_id: int, user_id: int, items: list) -> list:
    """
    نسخه‌ی سریع برای پیام‌های گروه: نتیجه‌ی اخیر را از کش می‌خواند و اگر چند پیام هم‌زمان
    از یک کاربر برسد، فقط یک بار get_chat_member می‌زند و همه از همان نتیجه استفاده می‌کنند.
    """
    key = (group_chat_id, user_id)
    hit = _membership_cache.get(key)
    if hit is not None:
        ts, missing_ids = hit
        ttl = MEMBERSHIP_MISS_TTL_SECONDS if missing_ids else MEMBERSHIP_OK_TTL_SECONDS
        if time.monotonic() - ts < ttl:
            return [it for it in items if it["id"] in missing_ids]

    task = _membership_inflight.get(key)
    if task is None:
        task = asyncio.ensure_future(get_missing_items(bot, user_id, items))
        _membership_inflight[key] = task

        def _cleanup(t: asyncio.Future, k=key) -> None:
            if _membership_inflight.get(k) is t:
                _membership_inflight.pop(k, None)

        task.add_done_callback(_cleanup)

    missing = await asyncio.shield(task)
    store_membership(group_chat_id, user_id, missing)
    return missing


def is_owner(user_id: int) -> bool:
    return user_id in SUPER_OWNER_IDS


# حالت‌های موقت پیوی مدیریت (کلید: user_id)
PENDING_TEXT_EDIT: dict = {}      # user_id -> (scope, key)
PENDING_ITEM_ADD: dict = {}       # user_id -> scope
PENDING_BOT_ADD: dict = {}        # user_id -> scope
PENDING_LINK_EDIT: dict = {}      # user_id -> item_id
PENDING_DELETE_TIMER: dict = {}   # user_id -> scope (همیشه یک گروه واقعی)


async def _delete_message_after(bot, chat_id: int, message_id: int, delay: float, user_id: Optional[int] = None) -> None:
    """بعد از delay ثانیه، پیام هشدار را پاک می‌کند تا کاربر در صورت نیاز هشدار جدید بگیرد."""
    if delay <= 0:
        return
    try:
        await asyncio.sleep(delay)
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except (BadRequest, Forbidden) as exc:
        logger.info("حذف خودکار پیام هشدار ناموفق بود (احتمالاً قبلاً حذف شده): %s", exc)
    except Exception as exc:  # noqa: BLE001
        logger.warning("خطا در حذف خودکار پیام هشدار: %s", exc)
    finally:
        if user_id is not None:
            key = (chat_id, user_id)
            active = _active_warn.get(key)
            if active is not None and active[0] == message_id:
                _active_warn.pop(key, None)


def _log_task_exception(task: asyncio.Task) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error("خطای پردازش‌نشده در تسک: %s", exc, exc_info=exc)


# ---------------------------------------------------------------------------
# هندلرهای گروه
# ---------------------------------------------------------------------------

_warn_locks: dict = {}    # (chat_id, user_id) -> Lock
_active_warn: dict = {}   # (chat_id, user_id) -> (message_id هشدار فعال، زمان انقضای اطمینان)

ANONYMOUS_ADMIN_BOT_ID = 1087968824       # GroupAnonymousBot: پیام ادمینِ ناشناس
GROUP_STAFF_TTL_SECONDS = 1200.0
_group_staff_cache: dict = {}             # (chat_id, user_id) -> (زمان، ادمین/مالک گروه است؟)
_bot_warned_users: set = set()            # (chat_id, user_id) که فقط آیتم «ربات» برایشان مانده و هشدار گرفته‌اند


def _get_warn_lock(chat_id: int, user_id: int) -> asyncio.Lock:
    key = (chat_id, user_id)
    if len(_warn_locks) > 4000:
        for k, lk in [(k, lk) for k, lk in _warn_locks.items() if not lk.locked()]:
            _warn_locks.pop(k, None)
            _active_warn.pop(k, None)
    lock = _warn_locks.get(key)
    if lock is None:
        lock = _warn_locks[key] = asyncio.Lock()
    return lock


async def delete_message_reliably(message, attempts: int = 5) -> bool:
    """حذف پیام با تلاش مجدد روی محدودیت نرخ (RetryAfter) و خطای شبکه."""
    for attempt in range(attempts):
        try:
            await message.delete()
            return True
        except RetryAfter as exc:
            wait = exc.retry_after
            wait = wait.total_seconds() if hasattr(wait, "total_seconds") else float(wait)
            logger.warning("محدودیت نرخ هنگام حذف پیام؛ %.1f ثانیه صبر و تلاش مجدد", wait)
            await asyncio.sleep(wait + 0.2)
        except (TimedOut, NetworkError) as exc:
            logger.warning("خطای شبکه هنگام حذف پیام (تلاش %d): %s", attempt + 1, exc)
            await asyncio.sleep(0.3 * (attempt + 1))
        except BadRequest as exc:
            if "not found" in str(exc).lower():
                return True
            logger.warning("عدم امکان حذف پیام: %s", exc)
            return False
        except Forbidden as exc:
            logger.warning("ربات اجازه‌ی حذف پیام ندارد: %s", exc)
            return False
    logger.error("حذف پیام بعد از %d تلاش ناموفق بود", attempts)
    return False


async def is_group_staff(bot, chat_id: int, user_id: int) -> bool:
    """مالک اصلی ربات، مالک گروه و ادمین/مالک واقعی گروه در تلگرام (با کش)."""
    if is_owner(user_id) or user_id == ANONYMOUS_ADMIN_BOT_ID:
        return True
    group = await get_group(chat_id)
    if group and group.get("owner_id") == user_id:
        return True
    key = (chat_id, user_id)
    now = time.monotonic()
    hit = _group_staff_cache.get(key)
    if hit and now - hit[0] < GROUP_STAFF_TTL_SECONDS:
        return hit[1]
    try:
        member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
        staff = member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER)
    except (BadRequest, Forbidden, TimedOut, NetworkError) as exc:
        logger.warning("بررسی ادمین بودن کاربر %s ممکن نبود: %s", user_id, exc)
        return False
    if len(_group_staff_cache) > 8000:
        _group_staff_cache.clear()
    _group_staff_cache[key] = (now, staff)
    return staff


async def on_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user

    if user is None or user.is_bot or message is None:
        return

    if message.sender_chat is not None:
        return  # ادمینِ ناشناس یا پست کانالِ متصل: هیچ‌وقت بررسی نمی‌شود
    if await is_group_staff(context.bot, chat.id, user.id):
        return

    items = await list_effective_items(chat.id)
    if not items:
        return

    missing = await get_missing_items_fast(context.bot, chat.id, user.id, items)
    if not missing:
        return

    warn_key = (chat.id, user.id)
    bot_only_missing = all(it.get("kind") == "bot" for it in missing)
    if bot_only_missing and warn_key in _bot_warned_users:
        _bot_warned_users.discard(warn_key)
        await asyncio.gather(*[record_bot_start(it["chat_id"], user.id) for it in missing])
        _membership_cache.pop(warn_key, None)
        return

    delete_task = asyncio.create_task(delete_message_reliably(message))
    delete_task.add_done_callback(_log_task_exception)

    group = await get_group(chat.id)
    delay = await get_warn_delete_seconds(group)

    async with _get_warn_lock(chat.id, user.id):
        active = _active_warn.get(warn_key)
        if active is not None:
            if time.monotonic() < active[1]:
                return  # هشدار این کاربر هنوز در گروه است؛ پیام‌ها فقط پاک می‌شوند
            _active_warn.pop(warn_key, None)

        keyboard = build_items_keyboard(missing, user.id)
        warn_msg = None
        for use_default in (False, True):
            text = await build_full_warn_text(group, user, missing, use_default=use_default)
            try:
                warn_msg = await context.bot.send_message(
                    chat_id=chat.id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=keyboard,
                    disable_web_page_preview=True,
                )
                break
            except RetryAfter as exc:
                wait = exc.retry_after
                wait = wait.total_seconds() if hasattr(wait, "total_seconds") else float(wait)
                await asyncio.sleep(wait + 0.2)
                try:
                    warn_msg = await context.bot.send_message(
                        chat_id=chat.id,
                        text=text,
                        parse_mode=ParseMode.HTML,
                        reply_markup=keyboard,
                        disable_web_page_preview=True,
                    )
                    break
                except TelegramError as exc2:
                    logger.error("ارسال پیام هشدار ناموفق بود: %s", exc2)
                    return
            except BadRequest as exc:
                logger.error("ارسال پیام هشدار ناموفق بود (use_default=%s): %s", use_default, exc)
            except (Forbidden, TimedOut, NetworkError) as exc:
                logger.error("ارسال پیام هشدار ناموفق بود: %s", exc)
                return
        if warn_msg is None:
            return
        if bot_only_missing:
            if len(_bot_warned_users) > 8000:
                _bot_warned_users.clear()
            _bot_warned_users.add(warn_key)
        expires_in = delay + 15.0 if delay > 0 else 3600.0
        _active_warn[warn_key] = (warn_msg.message_id, time.monotonic() + expires_in)

    if delay > 0:
        task = asyncio.create_task(
            _delete_message_after(context.bot, chat.id, warn_msg.message_id, delay, user.id)
        )
        task.add_done_callback(_log_task_exception)


async def _edit_warning_message(bot, chat_id: int, message_id: int, user: User, missing: list) -> None:
    """پیام هشدار را ادیت می‌کند: اگر چیزی باقی نمانده متن تایید عضویت، وگرنه فقط موارد باقی‌مانده."""
    group = await get_group(chat_id)
    for use_default in (False, True):
        if missing:
            text = await build_full_warn_text(group, user, missing, use_default=use_default)
            markup = build_items_keyboard(missing, user.id)
        else:
            template = DEFAULT_JOINED_TEXT
            if not use_default and group and group.get("joined_text"):
                template = group["joined_text"]
            text = render_template(template, user)
            markup = None
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=markup,
                disable_web_page_preview=True,
            )
            return
        except BadRequest as exc:
            if "not modified" in str(exc).lower() or "not found" in str(exc).lower():
                return
            logger.warning("ادیت خودکار پیام هشدار ناموفق (use_default=%s): %s", use_default, exc)
        except (Forbidden, TimedOut, NetworkError) as exc:
            logger.warning("ادیت خودکار پیام هشدار ناموفق: %s", exc)
            return


async def on_chat_member_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    تایید خودکار: وقتی کاربر در یکی از کانال‌ها/گروه‌های جوین اجباری عضو می‌شود، بدون زدن
    «بررسی عضویت» پیام هشدارش در هر گروهی که هشدار فعال دارد ادیت می‌شود.
    ربات باید در آن کانال/گروه ادمین باشد تا تلگرام رویداد chat_member را بفرستد.
    """
    cmu = update.chat_member
    if cmu is None:
        return
    member = cmu.new_chat_member
    user = member.user
    if user.is_bot:
        return

    joined = member.status in (
        ChatMemberStatus.MEMBER,
        ChatMemberStatus.ADMINISTRATOR,
        ChatMemberStatus.OWNER,
    ) or (member.status == ChatMemberStatus.RESTRICTED and getattr(member, "is_member", False))
    if not joined:
        return

    # این کاربر در کدام گروه‌ها الان هشدار فعال دارد؟ (فقط همین‌ها را بررسی می‌کنیم، نه کل دیتابیس)
    affected = [key for key in list(_active_warn.keys()) if key[1] == user.id]
    if not affected:
        return

    for chat_id, uid in affected:
        async with _get_warn_lock(chat_id, uid):
            active = _active_warn.get((chat_id, uid))
            if active is None:
                continue
            message_id, _expires = active
            items = await list_effective_items(chat_id)
            real_items = [it for it in items if it.get("kind") != "bot"]
            bot_items = [it for it in items if it.get("kind") == "bot"]

            missing_real = await get_missing_items(context.bot, uid, real_items)
            missing_bot: list = []
            if bot_items:
                if not missing_real:
                    await asyncio.gather(*[record_bot_start(it["chat_id"], uid) for it in bot_items])
                else:
                    missing_bot = await get_missing_items(context.bot, uid, bot_items)

            missing = missing_real + missing_bot
            store_membership(chat_id, uid, missing)
            await _edit_warning_message(context.bot, chat_id, message_id, user, missing)
            if not missing:
                _active_warn.pop((chat_id, uid), None)


async def _guard_button_owner(query, owner_part: str) -> bool:
    """دکمه‌های پیام هشدار فقط برای کاربرِ هدفِ پیام فعال هستند."""
    if owner_part.isdigit() and int(owner_part) != query.from_user.id:
        await query.answer("این دکمه برای شما نیست، پیام خودتان را بفرستید.", show_alert=True)
        return False
    return True


async def on_check_membership(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = query.from_user
    chat = update.effective_chat  # همان گروهی که دکمه در آن کلیک شده

    if not await _guard_button_owner(query, query.data.rpartition("_")[2]):
        return

    try:
        items = await list_effective_items(chat.id)
        await asyncio.gather(
            *[record_bot_start(it["chat_id"], user.id) for it in items if it.get("kind") == "bot"]
        )
        missing = await get_missing_items(context.bot, user.id, items)
        store_membership(chat.id, user.id, missing)
        if not missing:
            _active_warn.pop((chat.id, user.id), None)
    except Exception as exc:  # noqa: BLE001
        logger.error("خطا در بررسی عضویت: %s", exc)
        await query.answer("خطای موقت، دوباره تلاش کنید.", show_alert=True)
        return

    if missing:
        group = await get_group(chat.id)
        for use_default in (False, True):
            text = await build_full_warn_text(group, user, missing, use_default=use_default)
            try:
                await query.edit_message_text(
                    text=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=build_items_keyboard(missing, user.id),
                    disable_web_page_preview=True,
                )
                await query.answer("هنوز در موارد باقی‌مانده عضو نشده‌اید ❌")
                return
            except BadRequest as exc:
                if "not modified" in str(exc).lower():
                    await query.answer("هنوز در موارد باقی‌مانده عضو نشده‌اید ❌", show_alert=True)
                    return
                logger.warning("ادیت پیام هشدار ناموفق (use_default=%s): %s", use_default, exc)
        await query.answer("هنوز در همه‌ی موارد عضو نشده‌اید ❌", show_alert=True)
        return

    group = await get_group(chat.id)
    for use_default in (False, True):
        template = DEFAULT_JOINED_TEXT
        if not use_default and group and group.get("joined_text"):
            template = group["joined_text"]
        text = render_template(template, user)
        try:
            await query.edit_message_text(text=text, parse_mode=ParseMode.HTML)
            break
        except BadRequest as exc:
            logger.info("ادیت پیام تایید ناموفق (use_default=%s): %s", use_default, exc)

    await query.answer("عضویت شما تایید شد ✅")


# ---------------------------------------------------------------------------
# ثبت خودکار گروه هنگام افزودن ربات
# ---------------------------------------------------------------------------


async def on_bot_membership_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """وقتی ربات به گروهی اضافه/ادمین می‌شود، همان کاربر به‌عنوان مالک آن گروه ثبت می‌شود."""
    cmu = update.my_chat_member
    if cmu is None:
        return
    chat = cmu.chat
    if chat.type not in (Chat.GROUP, Chat.SUPERGROUP):
        return

    new_status = cmu.new_chat_member.status
    if new_status not in (ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR):
        return  # ربات حذف/خارج/بن شده: چیزی برای ثبت نیست

    actor = cmu.from_user
    await upsert_group_owner(chat.id, actor.id, chat.title or str(chat.id))

    note = (
        f"ربات «{BOT_DISPLAY_NAME}» به گروه «{html.escape(chat.title or '')}» اضافه شد ✅\n"
        "برای تنظیم جوین اجباریِ این گروه (افزودن کانال/گروه/ربات، متن‌ها و زمان حذف پیام)، "
        "به پیوی همین ربات بیایید و /start را بزنید.\n\n"
        "نکته: برای اینکه ربات بتواند عضویت را در کانال/گروه‌های دیگر چک کند، باید در "
        "آن‌ها هم ادمین باشد."
    )
    try:
        await context.bot.send_message(chat_id=actor.id, text=note, parse_mode=ParseMode.HTML)
    except (BadRequest, Forbidden):
        pass  # کاربر هنوز پیوی ربات را استارت نکرده؛ مشکلی نیست، از /start خودش می‌بیند


# ---------------------------------------------------------------------------
# پنل مدیریت (پیوی ربات)
# ---------------------------------------------------------------------------

MAIN_MENU_BUTTONS = [
    [InlineKeyboardButton("👥 گروه‌های من", callback_data="mygroups")],
]

OWNER_EXTRA_BUTTONS = [
    [InlineKeyboardButton("📡 آیتم‌های سراسری (همه‌ی گروه‌ها)", callback_data="global")],
    [InlineKeyboardButton("🗂 همه‌ی گروه‌های ربات", callback_data="allgroups")],
]


def main_menu_kb(user_id: int) -> InlineKeyboardMarkup:
    rows = list(MAIN_MENU_BUTTONS)
    if is_owner(user_id):
        rows += OWNER_EXTRA_BUTTONS
    return InlineKeyboardMarkup(rows)


def back_kb(callback_data: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data=callback_data)]])


def scope_panel_kb(scope: str) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton("📋 مدیریت آیتم‌ها", callback_data=f"g:{scope}:channels")]]
    if scope != GLOBAL_SCOPE:
        rows += [
            [InlineKeyboardButton("✏️ ویرایش متن‌ها", callback_data=f"g:{scope}:texts")],
            [InlineKeyboardButton("⏱ زمان حذف پیام هشدار", callback_data=f"g:{scope}:timer")],
        ]
    rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="menu_main")])
    return InlineKeyboardMarkup(rows)


def channels_menu_kb(scope: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("➕ افزودن کانال/گروه", callback_data=f"g:{scope}:ch_add")],
            [InlineKeyboardButton("🤖 افزودن ربات", callback_data=f"g:{scope}:ch_add_bot")],
            [InlineKeyboardButton("📋 لیست آیتم‌ها", callback_data=f"g:{scope}:ch_list")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data=f"g:{scope}:panel")],
        ]
    )


def texts_menu_kb(scope: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✏️ متن هشدار", callback_data=f"g:{scope}:txt_warn")],
            [InlineKeyboardButton("✏️ متن تایید عضویت", callback_data=f"g:{scope}:txt_joined")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data=f"g:{scope}:panel")],
        ]
    )


def list_items_kb(scope: str, items: list) -> InlineKeyboardMarkup:
    rows = []
    for it in items:
        icon = KIND_ICON.get(it.get("kind", "channel"), "📢")
        rows.append([InlineKeyboardButton(f"{icon} {it['title']}", callback_data=f"g:{scope}:ch_view:{it['id']}")])
    rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data=f"g:{scope}:channels")])
    return InlineKeyboardMarkup(rows)


def item_manage_kb(scope: str, item: dict) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✏️ تغییر لینک", callback_data=f"g:{scope}:ch_editlink:{item['id']}")],
            [InlineKeyboardButton("🗑 حذف", callback_data=f"g:{scope}:ch_del:{item['id']}")],
            [InlineKeyboardButton("🔙 بازگشت به لیست", callback_data=f"g:{scope}:ch_list")],
        ]
    )


def groups_list_kb(groups: list, back_data: str = "menu_main") -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(f"👥 {g.get('title') or g['id']}", callback_data=f"g:{g['id']}:panel")] for g in groups]
    rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data=back_data)])
    return InlineKeyboardMarkup(rows)


ADD_ITEM_PROMPT = (
    "برای افزودن <b>کانال</b> یا <b>گروه</b> (ربات باید ادمین آن باشد)، یکی از راه‌های زیر:\n\n"
    "۱) فوروارد یک پیام از آن کانال/گروه\n"
    "۲) ارسال مستقیم یوزرنیم: <code>@channel_username</code>\n"
    "۳) ارسال مستقیم لینک عمومی: <code>https://t.me/channel_username</code>\n"
    "۴) ارسال مستقیم آیدی عددی (اگر ربات از قبل عضو/ادمین آن است): <code>-1001234567890</code>\n\n"
    "برای کانال/گروه <b>خصوصی</b> که فقط لینک دعوت (+…) دارید، لطفاً فوروارد کنید؛ "
    "یا اگر آیدی عددی را می‌دانید:\n"
    "<code>-1001234567890 | https://t.me/+AbCdEfGhIj</code>\n\n"
    "اگر لینک ندارید ولی ربات ادمین است، فقط یوزرنیم/آیدی/فوروارد کافیست؛ لینک خودکار ساخته می‌شود."
)

ADD_BOT_PROMPT = (
    "یکی از این‌ها را ارسال کنید:\n\n"
    "۱) یوزرنیم ربات: <code>@id_bot</code>\n"
    "۲) لینک ربات: <code>https://t.me/id_bot</code>\n"
    "۳) لینک دعوت با پارامتر استارت: <code>https://t.me/id_bot?start=ref123</code>\n\n"
    "دکمه‌ی این ربات یک لینک مستقیم است و کاربر با زدن آن به پیوی ربات هدایت می‌شود. "
    "ورودش وقتی تایید می‌شود که «بررسی عضویت» را بزند. نیازی به تغییر در ربات مقصد نیست."
)


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat.type != Chat.PRIVATE:
        return
    user = update.effective_user

    if user is not None and context.bot.username:
        await record_bot_start(context.bot.username, user.id)

    PENDING_ITEM_ADD.pop(user.id, None)
    PENDING_BOT_ADD.pop(user.id, None)
    PENDING_LINK_EDIT.pop(user.id, None)
    PENDING_TEXT_EDIT.pop(user.id, None)
    PENDING_DELETE_TIMER.pop(user.id, None)

    my_groups = await list_groups_by_owner(user.id)
    if is_owner(user.id) or my_groups:
        await update.message.reply_text(
            f"به پنل مدیریت «{BOT_DISPLAY_NAME}» خوش آمدید 👋", reply_markup=main_menu_kb(user.id)
        )
        return

    await update.message.reply_text(
        f"سلام! «{BOT_DISPLAY_NAME}» یک ربات رایگان و عمومیِ جوین اجباری است.\n\n"
        "برای استفاده، ربات را به گروه خودتان اضافه و <b>ادمین</b> کنید؛ همان لحظه شما مالک "
        "آن گروه در این ربات می‌شوید و با زدن دوباره‌ی /start اینجا می‌توانید جوین اجباری‌های "
        "همان گروه را تنظیم کنید.",
        parse_mode=ParseMode.HTML,
    )


async def owner_panel_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data
    await query.answer()

    # ---- مسیرهای ثابت ----
    if data == "menu_main":
        await query.edit_message_text(f"پنل مدیریت «{BOT_DISPLAY_NAME}»:", reply_markup=main_menu_kb(user_id))
        return

    if data == "mygroups":
        groups = await list_groups_by_owner(user_id)
        if not groups:
            await query.edit_message_text(
                "شما هنوز مالک هیچ گروهی نیستید. ربات را در گروه خودتان ادمین کنید.",
                reply_markup=back_kb("menu_main"),
            )
            return
        await query.edit_message_text("یکی از گروه‌های خود را انتخاب کنید:", reply_markup=groups_list_kb(groups))
        return

    if data == "allgroups":
        if not is_owner(user_id):
            await query.answer("فقط مالک اصلی ربات به این بخش دسترسی دارد.", show_alert=True)
            return
        groups = await list_all_groups()
        if not groups:
            await query.edit_message_text("هنوز هیچ گروهی ثبت نشده است.", reply_markup=back_kb("menu_main"))
            return
        await query.edit_message_text("همه‌ی گروه‌های ربات:", reply_markup=groups_list_kb(groups))
        return

    if data == "global":
        if not is_owner(user_id):
            await query.answer("فقط مالک اصلی ربات به این بخش دسترسی دارد.", show_alert=True)
            return
        await query.edit_message_text(
            "📡 آیتم‌های سراسری — این‌ها در جوین اجباریِ <b>همه‌ی گروه‌های ربات</b> اعمال می‌شوند.",
            parse_mode=ParseMode.HTML,
            reply_markup=scope_panel_kb(GLOBAL_SCOPE),
        )
        return

    if not data.startswith("g:"):
        return  # دیتای ناشناخته

    # ---- مسیرهای مرتبط با یک scope (گروه یا سراسری) ----
    _, scope, rest = data.split(":", 2)
    group = None if scope == GLOBAL_SCOPE else await get_group(int(scope))

    if not can_manage_scope(scope, user_id, group):
        await query.answer("شما اجازه‌ی مدیریت این گروه را ندارید.", show_alert=True)
        return

    if rest != "ch_add":
        PENDING_ITEM_ADD.pop(user_id, None)
    if rest != "ch_add_bot":
        PENDING_BOT_ADD.pop(user_id, None)
    if rest != "timer":
        PENDING_DELETE_TIMER.pop(user_id, None)

    title = html.escape((group or {}).get("title") or "سراسری")

    if rest == "panel":
        label = "📡 آیتم‌های سراسری" if scope == GLOBAL_SCOPE else f"👥 گروه: {title}"
        await query.edit_message_text(f"{label}\nیکی از گزینه‌ها را انتخاب کنید:", parse_mode=ParseMode.HTML, reply_markup=scope_panel_kb(scope))
        return

    if rest == "channels":
        await query.edit_message_text("مدیریت آیتم‌های جوین اجباری:", reply_markup=channels_menu_kb(scope))
        return

    if rest == "texts":
        await query.edit_message_text("ویرایش متن‌ها:", reply_markup=texts_menu_kb(scope))
        return

    if rest == "timer":
        current = await get_warn_delete_seconds(group)
        PENDING_DELETE_TIMER[user_id] = scope
        await query.edit_message_text(
            f"زمان فعلی حذف خودکار پیام هشدار: <b>{current:g}</b> ثانیه.\n"
            "یک عدد غیرمنفی بفرستید (۰ یعنی حذف خودکار غیرفعال).",
            parse_mode=ParseMode.HTML,
            reply_markup=back_kb(f"g:{scope}:panel"),
        )
        return

    if rest == "ch_add":
        PENDING_ITEM_ADD[user_id] = scope
        await query.edit_message_text(ADD_ITEM_PROMPT, parse_mode=ParseMode.HTML, reply_markup=back_kb(f"g:{scope}:channels"))
        return

    if rest == "ch_add_bot":
        PENDING_BOT_ADD[user_id] = scope
        await query.edit_message_text(ADD_BOT_PROMPT, parse_mode=ParseMode.HTML, reply_markup=back_kb(f"g:{scope}:channels"))
        return

    if rest == "ch_list":
        items = await list_scope_items(scope)
        if not items:
            await query.edit_message_text("هیچ آیتمی ثبت نشده است.", reply_markup=back_kb(f"g:{scope}:channels"))
        else:
            await query.edit_message_text("یکی از موارد زیر را برای مدیریت انتخاب کنید:", reply_markup=list_items_kb(scope, items))
        return

    if rest.startswith("ch_view:"):
        item_id = int(rest.split(":")[1])
        item = await get_item(item_id)
        if not item:
            await query.edit_message_text("این آیتم دیگر وجود ندارد.", reply_markup=back_kb(f"g:{scope}:ch_list"))
            return
        label = KIND_LABEL.get(item.get("kind", "channel"), "کانال")
        text = (
            f"مدیریت {label}: <b>{html.escape(item['title'])}</b>\n"
            f"شناسه: <code>{item['chat_id']}</code>\n"
            f"لینک: {item['invite_link']}"
        )
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=item_manage_kb(scope, item))
        return

    if rest.startswith("ch_editlink:"):
        item_id = int(rest.split(":")[1])
        PENDING_LINK_EDIT[user_id] = item_id
        await query.edit_message_text("لینک جدید را ارسال کنید:", reply_markup=back_kb(f"g:{scope}:ch_view:{item_id}"))
        return

    if rest.startswith("ch_del:"):
        item_id = int(rest.split(":")[1])
        removed = await remove_item_by_id(item_id)
        items = await list_scope_items(scope)
        msg = "حذف شد ✅" if removed else "حذف نشد، دوباره تلاش کنید."
        if items:
            await query.edit_message_text(f"{msg}\n\nیکی از موارد زیر را برای مدیریت انتخاب کنید:", reply_markup=list_items_kb(scope, items))
        else:
            await query.edit_message_text(f"{msg}\n\nهیچ آیتمی ثبت نشده است.", reply_markup=back_kb(f"g:{scope}:channels"))
        return

    if rest in ("txt_warn", "txt_joined"):
        key = "warn_text" if rest == "txt_warn" else "joined_text"
        PENDING_TEXT_EDIT[user_id] = (scope, key)
        example = DEFAULT_WARN_TEXT if key == "warn_text" else DEFAULT_JOINED_TEXT
        await query.edit_message_text(
            "متن جدید را ارسال کنید. از <code>{mention}</code> برای جای منشن کاربر استفاده کنید.\n\n"
            f"نمونه‌ی پیش‌فرض:\n<code>{html.escape(example)}</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=back_kb(f"g:{scope}:texts"),
        )
        return


# ---------------------------------------------------------------------------
# پردازش ورودی‌های متنیِ پیوی
# ---------------------------------------------------------------------------


def parse_chat_ref(text: str):
    """متن را به (ref قابل‌استفاده در get_chat، لینک خصوصیِ احتمالی) تبدیل می‌کند."""
    text = text.strip()
    m = re.match(r"^(?:https?://)?(?:t\.me|telegram\.me)/\+([A-Za-z0-9_-]+)/?$", text, re.IGNORECASE)
    if m:
        return None, f"https://t.me/+{m.group(1)}"
    m = re.match(r"^(?:https?://)?(?:t\.me|telegram\.me)/joinchat/([A-Za-z0-9_-]+)/?$", text, re.IGNORECASE)
    if m:
        return None, f"https://t.me/joinchat/{m.group(1)}"
    m = re.match(r"^(?:https?://)?(?:t\.me|telegram\.me)/([A-Za-z0-9_]{5,32})/?$", text, re.IGNORECASE)
    if m:
        return f"@{m.group(1)}", None
    if text.startswith("@"):
        return text, None
    if re.match(r"^-?\d+$", text):
        return int(text), None
    m = re.match(r"^[A-Za-z0-9_]{5,32}$", text)
    if m:
        return f"@{text}", None
    return None, None


async def owner_private_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user_id = update.effective_user.id
    if message is None:
        return

    # ---- افزودن کانال/گروه ----
    if user_id in PENDING_ITEM_ADD:
        scope = PENDING_ITEM_ADD[user_id]
        group = None if scope == GLOBAL_SCOPE else await get_group(int(scope))
        if not can_manage_scope(scope, user_id, group):
            PENDING_ITEM_ADD.pop(user_id, None)
            return

        async def _finish_add(chat_full, forced_link: Optional[str] = None):
            PENDING_ITEM_ADD.pop(user_id, None)
            kind = "group" if chat_full.type in (Chat.GROUP, Chat.SUPERGROUP) else "channel"
            link = forced_link
            if link is None:
                if chat_full.username:
                    link = f"https://t.me/{chat_full.username}"
                else:
                    try:
                        invite = await context.bot.create_chat_invite_link(chat_full.id)
                        link = invite.invite_link
                    except (BadRequest, Forbidden) as exc:
                        await message.reply_text(
                            "ربات نتوانست لینک دعوت بسازد (احتمالاً ادمین آن کانال/گروه نیست). "
                            f"لینک را به‌صورت دستی بفرستید یا ربات را ادمین کنید.\n({exc})"
                        )
                        PENDING_ITEM_ADD[user_id] = scope
                        return
            err = await add_item(scope, kind, str(chat_full.id), chat_full.title or str(chat_full.id), link)
            if err:
                await message.reply_text(f"❌ ذخیره در دیتابیس شکست خورد:\n<code>{err}</code>", parse_mode=ParseMode.HTML)
                return
            await message.reply_text(
                f"«{html.escape(chat_full.title or '')}» اضافه شد ✅", reply_markup=channels_menu_kb(scope)
            )

        if message.forward_from_chat is not None:
            await _finish_add(message.forward_from_chat)
            return

        text = (message.text or "").strip()
        if "|" in text:
            ref_part, link_part = (p.strip() for p in text.split("|", 1))
            try:
                chat_id_num = int(ref_part)
            except ValueError:
                await message.reply_text("فرمت نامعتبر است. مثال: <code>-1001234567890 | https://t.me/+AbCdEfGhIj</code>", parse_mode=ParseMode.HTML)
                return
            try:
                chat_full = await context.bot.get_chat(chat_id_num)
            except (BadRequest, Forbidden) as exc:
                await message.reply_text(f"خطا در دسترسی: {exc}")
                return
            if chat_full.type not in (Chat.CHANNEL, Chat.GROUP, Chat.SUPERGROUP):
                await message.reply_text("این یک کانال یا گروه نیست.")
                return
            await _finish_add(chat_full, forced_link=link_part)
            return

        ref, private_link = parse_chat_ref(text)
        if ref is not None:
            try:
                chat_full = await context.bot.get_chat(ref)
            except (BadRequest, Forbidden) as exc:
                await message.reply_text(f"خطا در دسترسی: {exc}")
                return
            if chat_full.type not in (Chat.CHANNEL, Chat.GROUP, Chat.SUPERGROUP):
                await message.reply_text("این یک کانال یا گروه نیست.")
                return
            await _finish_add(chat_full)
            return

        if private_link is not None:
            await message.reply_text(
                "این یک لینک دعوت خصوصی است و ربات نمی‌تواند فقط از روی آن، کانال/گروه را resolve کند. "
                "یکی از راه‌های زیر را امتحان کنید:\n\n"
                "۱) ربات را ادمین آن کانال/گروه کنید و یک پیام از آن را برای من فوروارد کنید.\n"
                "۲) اگر آیدی عددی کانال/گروه را می‌دانید:\n"
                f"<code>-1001234567890 | {private_link}</code>",
                parse_mode=ParseMode.HTML,
            )
            return

        await message.reply_text(
            "فرمت نامعتبر است. یکی از این‌ها را بفرستید: یوزرنیم (@channel)، لینک عمومی t.me/... ، "
            "آیدی عددی، یا فوروارد یک پیام از آن کانال/گروه.",
            parse_mode=ParseMode.HTML,
        )
        return

    # ---- افزودن ربات ----
    if user_id in PENDING_BOT_ADD:
        scope = PENDING_BOT_ADD[user_id]
        group = None if scope == GLOBAL_SCOPE else await get_group(int(scope))
        if not can_manage_scope(scope, user_id, group):
            PENDING_BOT_ADD.pop(user_id, None)
            return
        PENDING_BOT_ADD.pop(user_id, None)
        raw = (message.text or "").strip()
        m = re.match(r"^(?:https?://)?(?:t\.me|telegram\.me)/([A-Za-z0-9_]{5,32})/?(?:\?(.*))?$", raw, re.IGNORECASE)
        if m:
            username = m.group(1)
            query_string = m.group(2) or ""
            deep_link = f"https://t.me/{username}" + (f"?{query_string}" if "start=" in query_string else "?start=verify_join")
        else:
            username = raw.lstrip("@")
            if not re.match(r"^[A-Za-z0-9_]{5,32}$", username):
                await message.reply_text("یوزرنیم یا لینک نامعتبر است.")
                return
            deep_link = f"https://t.me/{username}?start=verify_join"

        title = username
        try:
            bot_chat = await context.bot.get_chat(f"@{username}")
            title = bot_chat.first_name or bot_chat.title or username
        except (BadRequest, Forbidden) as exc:
            logger.info("گرفتن اطلاعات ربات %s ممکن نبود: %s", username, exc)

        err = await add_item(scope, "bot", username, title, deep_link)
        if err:
            await message.reply_text(f"❌ ذخیره در دیتابیس شکست خورد:\n<code>{err}</code>", parse_mode=ParseMode.HTML)
            return
        await message.reply_text(
            f"ربات «{html.escape(title)}» اضافه شد ✅\nلینک استارت: {deep_link}",
            reply_markup=channels_menu_kb(scope),
            disable_web_page_preview=True,
        )
        return

    # ---- ویرایش لینک آیتم ----
    if user_id in PENDING_LINK_EDIT:
        item_id = PENDING_LINK_EDIT.pop(user_id)
        item = await get_item(item_id)
        if not item:
            await message.reply_text("این آیتم دیگر وجود ندارد.")
            return
        scope = GLOBAL_SCOPE if item.get("group_id") is None else str(item["group_id"])
        group = None if scope == GLOBAL_SCOPE else await get_group(int(scope))
        if not can_manage_scope(scope, user_id, group):
            return
        new_link = (message.text or "").strip()
        if not new_link:
            await message.reply_text("لینک نامعتبر است.")
            return
        err = await update_item_link(item_id, new_link)
        if err:
            await message.reply_text(f"❌ ذخیره در دیتابیس شکست خورد:\n<code>{err}</code>", parse_mode=ParseMode.HTML)
            return
        await message.reply_text("لینک به‌روزرسانی شد ✅", reply_markup=channels_menu_kb(scope))
        return

    # ---- تنظیم زمان حذف خودکار پیام هشدار ----
    if user_id in PENDING_DELETE_TIMER:
        scope = PENDING_DELETE_TIMER.pop(user_id)
        if scope == GLOBAL_SCOPE:
            return
        group = await get_group(int(scope))
        if not can_manage_scope(scope, user_id, group):
            return
        raw = (message.text or "").strip().replace(",", ".")
        try:
            seconds = float(raw)
            if seconds < 0:
                raise ValueError
        except ValueError:
            await message.reply_text("عدد نامعتبر است. یک عدد غیرمنفی ارسال کنید (مثلاً 5 یا 0).")
            return
        err = await set_group_field(int(scope), "delete_seconds", seconds)
        if err:
            await message.reply_text(f"❌ ذخیره در دیتابیس شکست خورد:\n<code>{err}</code>", parse_mode=ParseMode.HTML)
            return
        note = "حذف خودکار غیرفعال شد." if seconds == 0 else f"پیام‌های هشدار بعد از {seconds:g} ثانیه پاک می‌شوند."
        await message.reply_text(f"ذخیره شد ✅\n{note}", reply_markup=scope_panel_kb(scope))
        return

    # ---- ویرایش متن‌ها ----
    if user_id in PENDING_TEXT_EDIT:
        scope, key = PENDING_TEXT_EDIT.pop(user_id)
        if scope == GLOBAL_SCOPE:
            return
        group = await get_group(int(scope))
        if not can_manage_scope(scope, user_id, group):
            return
        new_text = message.text_html or ""
        err = await set_group_field(int(scope), key, new_text)
        if err:
            await message.reply_text(f"❌ ذخیره در دیتابیس شکست خورد:\n<code>{err}</code>", parse_mode=ParseMode.HTML)
            return
        await message.reply_text("متن با موفقیت به‌روزرسانی شد ✅", reply_markup=texts_menu_kb(scope))
        return


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """هندلر سراسری خطا؛ جلوگیری از کرش کل ربات به‌خاطر یک آپدیت خراب."""
    if isinstance(context.error, Conflict):
        logger.error(
            "خطای Conflict: یک نمونه‌ی دیگر از همین ربات هم‌زمان در حال اجراست. "
            "مطمئن شوید فقط یک instance از سرویس در حال اجراست."
        )
        return
    logger.error("خطای پردازش‌نشده: %s", context.error, exc_info=context.error)


# ---------------------------------------------------------------------------
# اجرای ربات (Webhook روی aiohttp)
# ---------------------------------------------------------------------------

WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET") or secrets.token_urlsafe(24)
WEBHOOK_PATH = f"/webhook/{WEBHOOK_SECRET}"
BASE_URL = (os.environ.get("RENDER_EXTERNAL_URL") or os.environ.get("WEBHOOK_URL", "")).rstrip("/")


async def _health(_request: web.Request) -> web.Response:
    return web.Response(text="OK")


async def _telegram_webhook(request: web.Request) -> web.Response:
    application: Application = request.app["application"]
    secret_header = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if secret_header != WEBHOOK_SECRET:
        return web.Response(status=403, text="forbidden")
    try:
        data = await request.json()
    except Exception:
        return web.Response(status=400, text="bad request")
    update = Update.de_json(data, application.bot)
    if update:
        await application.update_queue.put(update)
    return web.Response(text="OK")


async def _on_startup(app: web.Application) -> None:
    application: Application = app["application"]
    await application.initialize()
    await application.start()
    try:
        await application.bot.set_my_name(name=BOT_DISPLAY_NAME)
    except TelegramError as exc:
        logger.warning("تغییر نام نمایشی ربات ممکن نشد: %s", exc)

    webhook_url = f"{BASE_URL}{WEBHOOK_PATH}"
    await application.bot.set_webhook(
        url=webhook_url,
        secret_token=WEBHOOK_SECRET,
        allowed_updates=Update.ALL_TYPES,
        max_connections=40,
        drop_pending_updates=False,
    )
    logger.info("وبهوک روی %s تنظیم شد", webhook_url)


async def _on_cleanup(app: web.Application) -> None:
    application: Application = app["application"]
    await application.bot.delete_webhook()
    await application.stop()
    await application.shutdown()


async def _process_update_queue(application: Application) -> None:
    while True:
        try:
            update = await application.update_queue.get()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error("خطا در دریافت از صف آپدیت: %s", exc, exc_info=exc)
            continue
        try:
            task = application.create_task(application.process_update(update))
            task.add_done_callback(_log_task_exception)
        except Exception as exc:  # noqa: BLE001
            logger.error("خطا در ایجاد تسک پردازش آپدیت: %s", exc, exc_info=exc)


def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("متغیر محیطی BOT_TOKEN باید تنظیم شود.")
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError("متغیرهای محیطی SUPABASE_URL و SUPABASE_KEY باید تنظیم شوند.")
    if not BASE_URL:
        raise RuntimeError(
            "آدرس عمومی سرویس پیدا نشد. اگر روی Render نیستید، متغیر محیطی "
            "WEBHOOK_URL را برابر آدرس عمومی سرویس‌تان (بدون / انتهایی) ست کنید."
        )

    request = HTTPXRequest(connect_timeout=15.0, read_timeout=30.0, write_timeout=15.0, pool_timeout=15.0)

    application: Application = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .request(request)
        .concurrent_updates(True)
        .build()
    )

    application.add_error_handler(on_error)

    application.add_handler(CommandHandler("start", start_cmd))
    application.add_handler(ChatMemberHandler(on_chat_member_update, ChatMemberHandler.CHAT_MEMBER))
    application.add_handler(ChatMemberHandler(on_bot_membership_update, ChatMemberHandler.MY_CHAT_MEMBER))

    application.add_handler(CallbackQueryHandler(on_check_membership, pattern=r"^check_membership(_\d+)?$"))
    application.add_handler(CallbackQueryHandler(owner_panel_router, pattern=r"^(menu_main$|mygroups$|global$|allgroups$|g:)"))

    application.add_handler(MessageHandler(filters.ChatType.GROUPS & ~filters.StatusUpdate.ALL, on_group_message))
    application.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.ALL, owner_private_message))

    web_app = web.Application()
    web_app["application"] = application
    web_app.router.add_get("/", _health)
    web_app.router.add_get("/healthz", _health)
    web_app.router.add_post(WEBHOOK_PATH, _telegram_webhook)
    web_app.on_startup.append(_on_startup)
    web_app.on_cleanup.append(_on_cleanup)

    port = int(os.environ.get("PORT", "10000"))
    logger.info("ربات در حال اجراست (webhook)...")

    async def _run_with_processor() -> None:
        runner = web.AppRunner(web_app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
        queue_task = asyncio.create_task(_process_update_queue(application))
        try:
            while True:
                await asyncio.sleep(3600)
        finally:
            queue_task.cancel()
            await runner.cleanup()

    asyncio.run(_run_with_processor())


if __name__ == "__main__":
    main()
