#!/usr/bin/env python3
"""
عضویت اجباریه سپر — ربات عمومی و رایگان جوین اجباری تلگرام (چند-مستاجری)
نیازمندی‌ها: python-telegram-bot==22.8  (پایتون 3.10+)
دیتابیس: Supabase (Postgres)
نصب: pip install -r requirements.txt

ساختار (نسخه‌ی چند-مستاجری):
- هر کاربر می‌تواند خودش گروه(های) خودش را ثبت کند و برای هرکدام آیتم‌های
  جوین اجباریِ مخصوص همان گروه تعریف کند (فقط در همان گروه اعمال می‌شود).
- مالک اصلی ربات (SUPER_OWNER_ID) می‌تواند «آیتم سراسری» اضافه کند؛ این آیتم‌ها
  به‌صورت خودکار برای همه‌ی گروه‌های ثبت‌شده در ربات اعمال می‌شوند.
- ثبت گروه فقط توسط کسی ممکن است که در آن گروه واقعاً ادمین/مالک باشد
  (با get_chat_member تایید می‌شود) تا کسی نتواند گروه دیگران را تصاحب کند.
- ربات باید در گروه و در همه‌ی کانال/گروه‌های جوین اجباری، ادمین باشد.

جدول‌های مورد نیاز در Supabase (SQL) — یک‌بار در SQL editor Supabase اجرا کنید:

    create table if not exists groups (
        group_id bigint primary key,
        owner_user_id bigint not null,
        title text,
        warn_delete_seconds real,
        created_at timestamptz not null default now()
    );

    create table if not exists channels (
        id bigint generated always as identity primary key,
        kind text not null default 'channel',       -- 'channel' | 'group' | 'bot'
        chat_id text not null,                       -- آیدی عددی کانال/گروه یا یوزرنیم ربات (بدون @)
        group_id bigint not null default 0,           -- 0 = سراسری (فقط مالک اصلی)، وگرنه آیدی گروه مالک این آیتم
        owner_user_id bigint,                         -- کاربری که این آیتم را اضافه کرده
        title text not null,
        invite_link text not null,
        expires_at timestamptz,
        start_members bigint,
        member_limit bigint,
        quota_done boolean not null default false,
        peak_members bigint not null default 0,
        unique (chat_id, group_id)
    );

    create table if not exists texts (
        key text not null,
        group_id bigint not null default 0,
        value text,
        primary key (key, group_id)
    );

    create table if not exists bot_starts (
        bot_username text not null,
        user_id bigint not null,
        started_at timestamptz not null default now(),
        primary key (bot_username, user_id)
    );

-- اگر از نسخه‌ی قبلی (تک‌گروهی) مهاجرت می‌کنید:
--   alter table channels add column if not exists group_id bigint not null default 0;
--   alter table channels add column if not exists owner_user_id bigint;
--   alter table channels drop constraint if exists channels_chat_id_key;
--   alter table channels add constraint channels_chat_id_group_id_key unique (chat_id, group_id);
--   alter table texts add column if not exists group_id bigint not null default 0;
--   alter table texts drop constraint if exists texts_pkey;
--   alter table texts add primary key (key, group_id);

نکته‌ی مهم درباره‌ی آیتم از نوع «ربات»:
دکمه‌ی ربات یک لینک مستقیم به t.me/BOT?start=... است. بررسی واقعی ممکن نیست؛
وقتی کاربر دکمه‌ی «بررسی عضویت» را می‌زند، ورود او به همه‌ی ربات‌ها تایید و در
جدول bot_starts ثبت می‌شود.
"""

import asyncio
import html
import logging
import os
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from aiohttp import web

from supabase import create_client, Client, ClientOptions
from postgrest import SyncPostgrestClient  # noqa: F401  (فقط برای وضوح وابستگی)

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

BOT_TOKEN = os.environ.get("BOT_TOKEN", "PUT_YOUR_BOT_TOKEN_HERE")
BOT_DISPLAY_NAME = "عضویت اجباریه سپر"

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

# مالک اصلیِ کل ربات. فقط همین آیدی می‌تواند آیتم «سراسری» اضافه کند
# (آیتمی که در همه‌ی گروه‌های ثبت‌شده‌ی ربات، برای همه‌ی کاربران، جوین اجباری می‌شود).
SUPER_OWNER_ID = int(os.environ.get("SUPER_OWNER_ID", "8977934490"))

# سنتینل group_id برای آیتم‌های سراسری (چون group_id واقعی تلگرام همیشه منفی است، صفر امن است)
GLOBAL_SCOPE = 0

DEFAULT_WARN_TEXT = "<b>کاربر {mention}\nبرای ارسال پیام باید در موارد زیر عضو شوید:</b>"
DEFAULT_JOINED_TEXT = "<b>کاربر {mention} در همه‌ی موارد عضو شد ✅</b>"

KIND_LABEL = {"channel": "کانال", "group": "گروه", "bot": "ربات"}
KIND_ICON = {"channel": "📢", "group": "👥", "bot": "🤖"}

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("forcejoin_bot")

# ---------------------------------------------------------------------------
# لایه دیتابیس (Supabase) — با هندل خطا تا یک خطای موقت دیتابیس ربات را نخواباند
# ---------------------------------------------------------------------------
#
# تمام تماس‌های supabase-py «سینک/بلاک‌کننده» هستند. برای اینکه event loop
# قفل نشود، هر متد این لایه از asyncio.to_thread استفاده می‌کند.

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


# کش کوتاه‌مدت سراسری: نتیجه‌ی موفق را نگه می‌دارد و با هر تغییر ادمین پاک می‌شود.
CACHE_TTL_SECONDS = 20.0
_db_cache: dict = {}

# گروه‌هایی که اخیراً برای یک chat_id ورودی پیام چک شده‌اند (بسیار داغ: هر پیام گروه این را می‌خواند)
GROUP_LOOKUP_TTL_SECONDS = 30.0
_group_lookup_cache: dict = {}  # chat_id -> (زمان، دیکشنری گروه یا None)


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
    _group_lookup_cache.clear()


# ---- گروه‌ها ---------------------------------------------------------------


async def get_group(group_id: int) -> Optional[dict]:
    hit, cached = _cache_get(f"group:{group_id}")
    if hit:
        return cached

    def _run():
        res = supabase.table("groups").select("*").eq("group_id", group_id).execute()
        value = res.data[0] if res.data else None
        _cache_put(f"group:{group_id}", value)
        return value

    return await asyncio.to_thread(_safe_db, _run, None)


async def get_group_by_chat(chat_id: int) -> Optional[dict]:
    """نسخه‌ی پرکاربرد برای هندلر پیام گروه؛ کش مخصوص خودش دارد (هر پیام این را صدا می‌زند)."""
    hit = _group_lookup_cache.get(chat_id)
    if hit is not None and time.monotonic() - hit[0] < GROUP_LOOKUP_TTL_SECONDS:
        return hit[1]
    group = await get_group(chat_id)
    _group_lookup_cache[chat_id] = (time.monotonic(), group)
    return group


async def get_groups_by_owner(user_id: int) -> list:
    def _run():
        res = supabase.table("groups").select("*").eq("owner_user_id", user_id).order("created_at").execute()
        return res.data or []

    return await asyncio.to_thread(_safe_db, _run, [])


async def register_group(group_id: int, owner_user_id: int, title: str) -> Optional[str]:
    """در صورت موفقیت None برمی‌گرداند، وگرنه متن خطا."""

    def _run():
        supabase.table("groups").upsert(
            {"group_id": group_id, "owner_user_id": owner_user_id, "title": title}
        ).execute()

    try:
        await asyncio.to_thread(_run)
        _cache_clear()
        return None
    except Exception as exc:  # noqa: BLE001
        logger.error("خطای دیتابیس هنگام ثبت گروه: %s", exc)
        return str(exc)


async def unregister_group(group_id: int) -> None:
    def _run():
        supabase.table("groups").delete().eq("group_id", group_id).execute()
        supabase.table("channels").delete().eq("group_id", group_id).execute()
        supabase.table("texts").delete().eq("group_id", group_id).execute()

    await asyncio.to_thread(_safe_db, _run)
    _cache_clear()


DEFAULT_WARN_DELETE_SECONDS = 5


async def get_warn_delete_seconds(group_id: int) -> float:
    group = await get_group(group_id)
    val = group.get("warn_delete_seconds") if group else None
    if val is None:
        return DEFAULT_WARN_DELETE_SECONDS
    try:
        return float(val)
    except (TypeError, ValueError):
        return DEFAULT_WARN_DELETE_SECONDS


async def set_warn_delete_seconds(group_id: int, seconds: float) -> Optional[str]:
    def _run():
        supabase.table("groups").update({"warn_delete_seconds": seconds}).eq("group_id", group_id).execute()

    try:
        await asyncio.to_thread(_run)
        _cache_clear()
        return None
    except Exception as exc:  # noqa: BLE001
        logger.error("خطای دیتابیس هنگام ذخیره‌ی زمان حذف: %s", exc)
        return str(exc)


# ---- آیتم‌های جوین اجباری ---------------------------------------------------


async def add_item(
    kind: str,
    chat_id: str,
    title: str,
    invite_link: str,
    group_id: int,
    owner_user_id: int,
    start_members: Optional[int] = None,
) -> Optional[str]:
    """در صورت موفقیت None برمی‌گرداند، در صورت خطا متن خطا را برمی‌گرداند."""

    def _run():
        payload = {
            "kind": kind,
            "chat_id": chat_id,
            "group_id": group_id,
            "owner_user_id": owner_user_id,
            "title": title,
            "invite_link": invite_link,
        }
        existing = (
            supabase.table("channels")
            .select("id,start_members")
            .eq("chat_id", chat_id)
            .eq("group_id", group_id)
            .execute()
            .data
        )
        if start_members is not None and not (existing and existing[0].get("start_members") is not None):
            payload["start_members"] = start_members
        supabase.table("channels").upsert(payload, on_conflict="chat_id,group_id").execute()

    try:
        await asyncio.to_thread(_run)
        _cache_clear()
        return None
    except Exception as exc:  # noqa: BLE001
        logger.error("خطای دیتابیس هنگام افزودن آیتم: %s", exc)
        return str(exc)


async def update_item_link(item_id: int, invite_link: str) -> Optional[str]:
    def _run():
        supabase.table("channels").update({"invite_link": invite_link}).eq("id", item_id).execute()

    try:
        await asyncio.to_thread(_run)
        _cache_clear()
        return None
    except Exception as exc:  # noqa: BLE001
        logger.error("خطای دیتابیس هنگام ویرایش لینک: %s", exc)
        return str(exc)


async def remove_item_by_id(item_id: int) -> bool:
    res = await asyncio.to_thread(
        _safe_db, lambda: supabase.table("channels").delete().eq("id", item_id).execute()
    )
    _cache_clear()
    return bool(res and res.data)


async def _fetch_items_for_group(group_id: int) -> list:
    """آیتم‌های سراسری (مالک اصلی) + آیتم‌های مخصوص همین گروه."""
    hit, cached = _cache_get(f"items:{group_id}")
    if hit:
        return cached

    def _run():
        res = (
            supabase.table("channels")
            .select("*")
            .in_("group_id", [GLOBAL_SCOPE, group_id])
            .order("id")
            .execute()
        )
        items = res.data or []
        _cache_put(f"items:{group_id}", items)
        return items

    return await asyncio.to_thread(_safe_db, _run, [])


def _parse_ts(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def item_is_expired(item: dict) -> bool:
    if item.get("quota_done"):
        return True
    expires_at = _parse_ts(item.get("expires_at"))
    return expires_at is not None and expires_at <= datetime.now(timezone.utc)


def format_duration(delta: timedelta) -> str:
    total = max(int(delta.total_seconds()), 0)
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    parts = []
    if days:
        parts.append(f"{days} روز")
    if hours:
        parts.append(f"{hours} ساعت")
    if minutes and not days:
        parts.append(f"{minutes} دقیقه")
    return " و ".join(parts) if parts else "کمتر از یک دقیقه"


def describe_item_schedule(item: dict) -> str:
    if item.get("quota_done"):
        return "⛔️ تعرفه‌ی ممبر کامل شد (دیگر جوین اجباری نیست)"
    expires_at = _parse_ts(item.get("expires_at"))
    if expires_at is None:
        return "فعال، بدون محدودیت زمانی"
    if item_is_expired(item):
        return "⛔️ منقضی شده (دیگر جوین اجباری نیست)"
    return f"فعال، {format_duration(expires_at - datetime.now(timezone.utc))} دیگر باقی مانده"


async def list_items(group_id: int) -> list:
    """آیتم‌های فعالِ جوین اجباری یک گروه (سراسری + مخصوص خودش؛ منقضی/تکمیل‌شده حذف می‌شوند)."""
    items = await _fetch_items_for_group(group_id)
    await _enforce_quotas(items)
    return [it for it in items if not item_is_expired(it)]


async def list_all_items(group_id: int) -> list:
    """همه‌ی آیتم‌های این گروه (شامل منقضی‌شده‌ها) برای پنل مدیریت."""
    return await _fetch_items_for_group(group_id)


async def get_item(group_id: int, item_id: int) -> Optional[dict]:
    for it in await list_all_items(group_id):
        if it["id"] == item_id:
            return it
    return None


EXPIRES_AT_MISSING_HINT = (
    "ستون expires_at در جدول channels وجود ندارد. این کوئری را در Supabase اجرا کنید:\n"
    "alter table channels add column if not exists expires_at timestamptz;"
)


async def set_item_expiry(item_id: int, expires_at: Optional[datetime]) -> Optional[str]:
    value = expires_at.isoformat() if expires_at else None

    def _run():
        supabase.table("channels").update({"expires_at": value}).eq("id", item_id).execute()

    try:
        await asyncio.to_thread(_run)
        _cache_clear()
        return None
    except Exception as exc:  # noqa: BLE001
        logger.error("خطای دیتابیس هنگام تنظیم زمان آیتم: %s", exc)
        if "expires_at" in str(exc):
            return EXPIRES_AT_MISSING_HINT
        return str(exc)


MEMBER_LIMIT_MISSING_HINT = (
    "ستون‌های تعرفه‌ی ممبر در جدول channels وجود ندارند. این کوئری‌ها را در Supabase اجرا کنید:\n"
    "alter table channels add column if not exists member_limit bigint;\n"
    "alter table channels add column if not exists quota_done boolean not null default false;"
)
MAX_MEMBER_LIMIT = 100_000_000
QUOTA_CHECK_INTERVAL_SECONDS = 3.0

_quota_bot = None
_quota_lock = asyncio.Lock()
_quota_last_check = 0.0


def item_member_limit(item: dict) -> int:
    try:
        return max(int(item.get("member_limit") or 0), 0)
    except (TypeError, ValueError):
        return 0


def format_quota(item: dict, joined: Optional[int]) -> str:
    limit = item_member_limit(item)
    if limit <= 0:
        return f"{format_count(joined)} / نامحدود"
    return f"{format_count(joined)} / {limit:,}"


async def set_item_quota(item_id: int, limit: int, baseline: Optional[int]) -> Optional[str]:
    payload: dict = {"member_limit": limit, "quota_done": False}
    if limit > 0 and baseline is not None:
        payload["start_members"] = baseline
        payload["peak_members"] = 0

    def _run():
        supabase.table("channels").update(payload).eq("id", item_id).execute()

    try:
        await asyncio.to_thread(_run)
        _cache_clear()
        _member_count_cache.clear()
        return None
    except Exception as exc:  # noqa: BLE001
        logger.error("خطای دیتابیس هنگام ثبت تعرفه‌ی ممبر: %s", exc)
        if "member_limit" in str(exc) or "quota_done" in str(exc):
            return MEMBER_LIMIT_MISSING_HINT
        return str(exc)


async def _mark_quota_done(item: dict) -> None:
    item["quota_done"] = True

    def _run():
        supabase.table("channels").update({"quota_done": True}).eq("id", item["id"]).execute()

    await asyncio.to_thread(_safe_db, _run, None)
    _cache_clear()
    logger.info("تعرفه‌ی ممبر «%s» کامل شد و از جوین اجباری کنار رفت.", item.get("title"))


async def _enforce_quotas(items: list) -> None:
    global _quota_last_check
    if _quota_bot is None:
        return
    pending = [
        it for it in items
        if item_member_limit(it) > 0 and not it.get("quota_done") and not item_is_expired(it)
    ]
    if not pending:
        return
    if time.monotonic() - _quota_last_check < QUOTA_CHECK_INTERVAL_SECONDS:
        return
    async with _quota_lock:
        if time.monotonic() - _quota_last_check < QUOTA_CHECK_INTERVAL_SECONDS:
            return
        _quota_last_check = time.monotonic()
        counts = await asyncio.gather(
            *(fetch_member_count(_quota_bot, it, force=True) for it in pending), return_exceptions=True
        )
        for it, joined in zip(pending, counts):
            if isinstance(joined, Exception) or joined is None:
                continue
            if joined >= item_member_limit(it):
                await _mark_quota_done(it)


_PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_DURATION_RE = re.compile(
    r"(\d+)\s*(m|min|mins|minute|minutes|دقیقه|h|hr|hrs|hour|hours|ساعت|d|day|days|روز)?"
)


def parse_duration(text: str) -> Optional[timedelta]:
    """مثال‌ها: 30m ، 12h ، 7d ، 90 دقیقه ، 2 روز ، فقط عدد = ساعت."""
    match = _DURATION_RE.fullmatch(text.translate(_PERSIAN_DIGITS).strip().lower())
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2) or "h"
    if unit.startswith(("m", "دقیقه")):
        delta = timedelta(minutes=amount)
    elif unit.startswith(("d", "روز")):
        delta = timedelta(days=amount)
    else:
        delta = timedelta(hours=amount)
    if delta <= timedelta(0) or delta > timedelta(days=3650):
        return None
    return delta


async def get_text(group_id: int, key: str, default: str) -> str:
    hit, cached = _cache_get(f"text:{group_id}:{key}")
    if hit:
        return cached

    def _run():
        res = supabase.table("texts").select("value").eq("key", key).eq("group_id", group_id).execute()
        value = res.data[0]["value"] if res.data else default
        _cache_put(f"text:{group_id}:{key}", value)
        return value

    return await asyncio.to_thread(_safe_db, _run, default)


async def set_text(group_id: int, key: str, value: str) -> Optional[str]:
    def _run():
        supabase.table("texts").upsert({"key": key, "group_id": group_id, "value": value}).execute()

    try:
        await asyncio.to_thread(_run)
        _cache_clear()
        return None
    except Exception as exc:  # noqa: BLE001
        logger.error("خطای دیتابیس هنگام ذخیره متن: %s", exc)
        return str(exc)


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


async def count_bot_starts(bot_username: str) -> int:
    def _run():
        res = (
            supabase.table("bot_starts")
            .select("user_id", count="exact")
            .eq("bot_username", bot_username.lower())
            .execute()
        )
        return res.count or 0

    return await asyncio.to_thread(_safe_db, _run, 0)


async def record_bot_start(bot_username: str, user_id: int) -> None:
    def _run():
        supabase.table("bot_starts").upsert(
            {"bot_username": bot_username.lower(), "user_id": user_id}
        ).execute()

    await asyncio.to_thread(_safe_db, _run)


# ---------------------------------------------------------------------------
# ابزارهای کمکی
# ---------------------------------------------------------------------------


def render_mention(user: User) -> str:
    name = user.first_name or "کاربر"
    name = name.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f'<a href="tg://user?id={user.id}">{name}</a>'


def render_template(template: str, user: User) -> str:
    mention = render_mention(user)
    text = template.replace("{mention}", mention)
    text = text.replace("منشن_کاربر", mention)
    if mention not in text:
        text = f"{mention}\n{text}"
    return text


def build_items_list_text(items: list) -> str:
    if not items:
        return ""
    lines = []
    for it in items:
        label = KIND_LABEL.get(it.get("kind", "channel"), "کانال")
        lines.append(f"{label}: {html.escape(it['title'])}")
    return "<blockquote>" + "\n".join(lines) + "</blockquote>"


async def build_full_warn_text(group_id: int, user: User, items: list, use_default: bool = False) -> str:
    intro_template = DEFAULT_WARN_TEXT if use_default else await get_text(group_id, "warn_text", DEFAULT_WARN_TEXT)
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
    rows.append([InlineKeyboardButton("✅ بررسی عضویت", callback_data=f"check_membership_{user_id}")])
    return InlineKeyboardMarkup(rows)


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


async def get_missing_items(bot, group_id: int, user_id: int, items: Optional[list] = None) -> list:
    if items is None:
        items = await list_items(group_id)
    if not items:
        return []
    results = await asyncio.gather(*[_check_single_item(bot, it, user_id) for it in items])
    return [it for it, ok in zip(items, results) if not ok]


MEMBERSHIP_OK_TTL_SECONDS = 20.0
MEMBERSHIP_MISS_TTL_SECONDS = 3.0
_membership_cache: dict = {}        # (group_id, user_id) -> (زمان، مجموعه‌ی id آیتم‌های ناقص)
_membership_inflight: dict = {}


def _mkey(group_id: int, user_id: int):
    return (group_id, user_id)


def store_membership(group_id: int, user_id: int, missing: list) -> None:
    if len(_membership_cache) > 5000:
        _membership_cache.clear()
    _membership_cache[_mkey(group_id, user_id)] = (time.monotonic(), {it["id"] for it in missing})


async def get_missing_items_fast(bot, group_id: int, user_id: int, items: list) -> list:
    key = _mkey(group_id, user_id)
    hit = _membership_cache.get(key)
    if hit is not None:
        ts, missing_ids = hit
        ttl = MEMBERSHIP_MISS_TTL_SECONDS if missing_ids else MEMBERSHIP_OK_TTL_SECONDS
        if time.monotonic() - ts < ttl:
            return [it for it in items if it["id"] in missing_ids]

    task = _membership_inflight.get(key)
    if task is None:
        task = asyncio.ensure_future(get_missing_items(bot, group_id, user_id, items))
        _membership_inflight[key] = task

        def _cleanup(t: asyncio.Future, k=key) -> None:
            if _membership_inflight.get(k) is t:
                _membership_inflight.pop(k, None)

        task.add_done_callback(_cleanup)

    missing = await asyncio.shield(task)
    store_membership(group_id, user_id, missing)
    return missing


def is_super_owner(user_id: int) -> bool:
    return user_id == SUPER_OWNER_ID


# حالت‌های موقت پیوی کاربران
PENDING_TEXT_EDIT: dict = {}
PENDING_ITEM_ADD: set = set()
PENDING_BOT_ADD: set = set()
PENDING_LINK_EDIT: dict = {}
PENDING_ITEM_TIME: dict = {}
PENDING_ITEM_QUOTA: dict = {}
PENDING_GROUP_REGISTER: set = set()
PENDING_DELETE_TIMER_SET: set = set()
ACTIVE_GROUP: dict = {}   # user_id -> group_id (گروهِ در حال مدیریت در پنل همان لحظه؛ GLOBAL_SCOPE = پنل سراسری)


async def _delete_message_after(bot, chat_id: int, message_id: int, delay: float, group_id: int, user_id: Optional[int] = None) -> None:
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
            key = _mkey(group_id, user_id)
            active = _active_warn.get(key)
            if active is not None and active[0] == message_id:
                _active_warn.pop(key, None)

# ---------------------------------------------------------------------------
# هندلرهای گروه
# ---------------------------------------------------------------------------


_warn_locks: dict = {}
_active_warn: dict = {}   # (group_id, user_id) -> (message_id، زمان انقضای اطمینان، chat_id گروه)


def _get_warn_lock(group_id: int, user_id: int) -> asyncio.Lock:
    key = _mkey(group_id, user_id)
    if len(_warn_locks) > 2000:
        for k, lk in list(_warn_locks.items()):
            if not lk.locked():
                _warn_locks.pop(k, None)
                _active_warn.pop(k, None)
    lock = _warn_locks.get(key)
    if lock is None:
        lock = _warn_locks[key] = asyncio.Lock()
    return lock


async def delete_message_reliably(message, attempts: int = 5) -> bool:
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


ANONYMOUS_ADMIN_BOT_ID = 1087968824
GROUP_STAFF_TTL_SECONDS = 120.0
_group_staff_cache: dict = {}             # (chat_id, user_id) -> (زمان، ادمین/مالک گروه است؟)
_bot_warned_users: set = set()            # (group_id, user_id) کاربرانی که فقط آیتم «ربات» برایشان مانده


async def is_group_staff(bot, chat_id: int, user_id: int, group_owner_id: Optional[int] = None) -> bool:
    """مالک ثبت‌کننده‌ی گروه، مالک اصلی ربات و ادمین/مالک واقعی گروه (با کش ۲ دقیقه‌ای)."""
    if is_super_owner(user_id) or user_id == group_owner_id or user_id == ANONYMOUS_ADMIN_BOT_ID:
        return True
    now = time.monotonic()
    key = (chat_id, user_id)
    hit = _group_staff_cache.get(key)
    if hit and now - hit[0] < GROUP_STAFF_TTL_SECONDS:
        return hit[1]
    try:
        member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
        staff = member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER)
    except (BadRequest, Forbidden, TimedOut, NetworkError) as exc:
        logger.warning("بررسی ادمین بودن کاربر %s ممکن نبود: %s", user_id, exc)
        return False
    if len(_group_staff_cache) > 5000:
        _group_staff_cache.clear()
    _group_staff_cache[key] = (now, staff)
    return staff


async def on_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user

    if user is None or user.is_bot or message is None:
        return

    group = await get_group_by_chat(chat.id)
    if group is None:
        return  # این گروه توسط هیچ‌کس در ربات ثبت نشده

    group_id = group["group_id"]

    if message.sender_chat is not None:
        return
    if await is_group_staff(context.bot, chat.id, user.id, group.get("owner_user_id")):
        return

    items = await list_items(group_id)
    if not items:
        return

    missing = await get_missing_items_fast(context.bot, group_id, user.id, items)
    if not missing:
        return

    bot_only_missing = all(it.get("kind") == "bot" for it in missing)
    warn_key = _mkey(group_id, user.id)
    if bot_only_missing and warn_key in _bot_warned_users:
        _bot_warned_users.discard(warn_key)
        await asyncio.gather(*[record_bot_start(it["chat_id"], user.id) for it in missing])
        _membership_cache.pop(warn_key, None)
        return

    await delete_message_reliably(message)

    delay = await get_warn_delete_seconds(group_id)

    async with _get_warn_lock(group_id, user.id):
        active = _active_warn.get(warn_key)
        if active is not None:
            if time.monotonic() < active[1]:
                return
            _active_warn.pop(warn_key, None)

        keyboard = build_items_keyboard(missing, user.id)
        warn_msg = None
        for use_default in (False, True):
            text = await build_full_warn_text(group_id, user, missing, use_default=use_default)
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
            if len(_bot_warned_users) > 5000:
                _bot_warned_users.clear()
            _bot_warned_users.add(warn_key)
        expires_in = delay + 15.0 if delay > 0 else 3600.0
        _active_warn[warn_key] = (warn_msg.message_id, time.monotonic() + expires_in, chat.id)

    if delay > 0:
        task = asyncio.create_task(
            _delete_message_after(context.bot, chat.id, warn_msg.message_id, delay, group_id, user.id)
        )
        task.add_done_callback(_log_task_exception)


async def _edit_warning_message(bot, group_id: int, chat_id: int, message_id: int, user: User, missing: list) -> None:
    for use_default in (False, True):
        if missing:
            text = await build_full_warn_text(group_id, user, missing, use_default=use_default)
            markup = build_items_keyboard(missing, user.id)
        else:
            template = DEFAULT_JOINED_TEXT if use_default else await get_text(group_id, "joined_text", DEFAULT_JOINED_TEXT)
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
    """تایید خودکار عضویت وقتی کاربر در یک کانال/گروهِ جوین‌اجباری (گروهی یا سراسری) عضو می‌شود."""
    cmu = update.chat_member
    if cmu is None:
        return

    member = cmu.new_chat_member
    user = member.user
    if user.is_bot:
        return

    global _quota_last_check
    chat_key = str(cmu.chat.id)

    def _find_groups():
        res = (
            supabase.table("channels")
            .select("group_id")
            .eq("chat_id", chat_key)
            .neq("kind", "bot")
            .execute()
        )
        return {row["group_id"] for row in (res.data or [])}

    scoped_group_ids = await asyncio.to_thread(_safe_db, _find_groups, set())
    if not scoped_group_ids:
        return

    if GLOBAL_SCOPE in scoped_group_ids:
        def _all_groups():
            res = supabase.table("groups").select("group_id").execute()
            return {row["group_id"] for row in (res.data or [])}

        scoped_group_ids = await asyncio.to_thread(_safe_db, _all_groups, scoped_group_ids)

    _quota_last_check = 0.0

    joined = member.status in (
        ChatMemberStatus.MEMBER,
        ChatMemberStatus.ADMINISTRATOR,
        ChatMemberStatus.OWNER,
    ) or (member.status == ChatMemberStatus.RESTRICTED and getattr(member, "is_member", False))
    if not joined:
        return

    for group_id in scoped_group_ids:
        warn_key = _mkey(group_id, user.id)
        items = await list_items(group_id)
        _membership_cache.pop(warn_key, None)

        async with _get_warn_lock(group_id, user.id):
            real_items = [it for it in items if it.get("kind") != "bot"]
            bot_items = [it for it in items if it.get("kind") == "bot"]

            if not await get_missing_items(context.bot, group_id, user.id, real_items) and bot_items:
                await asyncio.gather(*[record_bot_start(it["chat_id"], user.id) for it in bot_items])

            missing = await get_missing_items(context.bot, group_id, user.id, items)
            store_membership(group_id, user.id, missing)

            active = _active_warn.get(warn_key)
            if active is None:
                continue
            message_id, _expires, warn_chat_id = active
            await _edit_warning_message(context.bot, group_id, warn_chat_id, message_id, user, missing)
            if not missing:
                _active_warn.pop(warn_key, None)


async def _guard_button_owner(query, owner_part: str) -> bool:
    if owner_part.isdigit() and int(owner_part) != query.from_user.id:
        await query.answer("این دکمه برای شما نیست، پیام خودتان را بفرستید.", show_alert=True)
        return False
    return True


async def on_check_membership(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = query.from_user
    chat = update.effective_chat

    if not await _guard_button_owner(query, query.data.rpartition("_")[2]):
        return

    group = await get_group_by_chat(chat.id)
    if group is None:
        await query.answer("این گروه دیگر توسط ربات مدیریت نمی‌شود.", show_alert=True)
        return
    group_id = group["group_id"]

    try:
        all_items = await list_items(group_id)
        await asyncio.gather(
            *[record_bot_start(it["chat_id"], user.id) for it in all_items if it.get("kind") == "bot"]
        )
        missing = await get_missing_items(context.bot, group_id, user.id, all_items)
        store_membership(group_id, user.id, missing)
        warn_key = _mkey(group_id, user.id)
        if not missing:
            _active_warn.pop(warn_key, None)
    except Exception as exc:  # noqa: BLE001
        logger.error("خطا در بررسی عضویت: %s", exc)
        await query.answer("خطای موقت، دوباره تلاش کنید.", show_alert=True)
        return

    if missing:
        for use_default in (False, True):
            text = await build_full_warn_text(group_id, user, missing, use_default=use_default)
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

    for use_default in (False, True):
        joined_template = DEFAULT_JOINED_TEXT if use_default else await get_text(group_id, "joined_text", DEFAULT_JOINED_TEXT)
        text = render_template(joined_template, user)
        try:
            await query.edit_message_text(text=text, parse_mode=ParseMode.HTML)
            break
        except BadRequest as exc:
            logger.info("ادیت پیام تایید ناموفق (use_default=%s): %s", use_default, exc)

    await query.answer("عضویت شما تایید شد ✅")


# ---------------------------------------------------------------------------
# پنل مدیریت (پیوی ربات) — عمومی: هرکس می‌تواند گروه خودش را مدیریت کند
# ---------------------------------------------------------------------------


def group_menu_kb(group_id: int) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("📋 مدیریت آیتم‌ها", callback_data="menu_channels", style="primary")],
    ]
    if group_id != GLOBAL_SCOPE:
        rows += [
            [InlineKeyboardButton("✏️ ویرایش متن‌ها", callback_data="menu_texts", style="primary")],
            [InlineKeyboardButton("⏱ زمان حذف پیام هشدار", callback_data="menu_delete_timer", style="primary")],
            [InlineKeyboardButton("ℹ️ وضعیت فعلی", callback_data="menu_status", style="success")],
            [InlineKeyboardButton("🗑 حذف این گروه از ربات", callback_data="grp_unregister", style="danger")],
        ]
    rows.append([InlineKeyboardButton("🔁 تغییر گروه", callback_data="grp_switch")])
    return InlineKeyboardMarkup(rows)


CHANNELS_MENU = InlineKeyboardMarkup(
    [
        [InlineKeyboardButton("➕ افزودن کانال/گروه", callback_data="ch_add", style="success")],
        [InlineKeyboardButton("🤖 افزودن ربات", callback_data="ch_add_bot", style="success")],
        [InlineKeyboardButton("📋 لیست کانال‌ها", callback_data="ch_list", style="primary")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="menu_main")],
    ]
)

TEXTS_MENU = InlineKeyboardMarkup(
    [
        [InlineKeyboardButton("✏️ ویرایش متن هشدار", callback_data="txt_warn", style="primary")],
        [InlineKeyboardButton("✏️ ویرایش متن تایید عضویت", callback_data="txt_joined", style="primary")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="menu_main")],
    ]
)


def build_schedule_keyboard(item_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("⚡ تنظیم هم اکنون", callback_data=f"ch_now_{item_id}", style="success"),
                InlineKeyboardButton("⏰ تنظیم زمان", callback_data=f"ch_time_{item_id}", style="primary"),
            ],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="menu_channels")],
        ]
    )


def back_kb(callback_data: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data=callback_data)]])


MEMBER_COUNT_TTL_SECONDS = 60.0
_member_count_cache: dict = {}


def format_count(count: Optional[int]) -> str:
    return f"{count:,}" if isinstance(count, int) else "—"


async def _save_start_members(item_id: int, value: int) -> None:
    def _run():
        supabase.table("channels").update({"start_members": value}).eq("id", item_id).execute()

    await asyncio.to_thread(_safe_db, _run, None)
    _cache_clear()


async def _save_peak_members(item_id: int, value: int) -> None:
    def _run():
        supabase.table("channels").update({"peak_members": value}).eq("id", item_id).execute()

    await asyncio.to_thread(_safe_db, _run, None)
    _cache_clear()


async def fetch_member_count(bot, item: dict, force: bool = False) -> Optional[int]:
    key = f"{item['chat_id']}:{item.get('group_id', 0)}"
    now = time.monotonic()
    hit = _member_count_cache.get(key)
    if hit and not force and now - hit[0] < MEMBER_COUNT_TTL_SECONDS:
        current = hit[1]
    else:
        try:
            if item.get("kind") == "bot":
                current = await count_bot_starts(item["chat_id"])
            else:
                current = await bot.get_chat_member_count(item["chat_id"])
        except (BadRequest, Forbidden, TimedOut, NetworkError) as exc:
            logger.warning("خطا در دریافت تعداد اعضای %s: %s", item.get("title"), exc)
            if not hit:
                return item.get("peak_members") or 0
            current = hit[1]
        else:
            _member_count_cache[key] = (now, current)

    baseline = item.get("start_members")
    if baseline is None:
        item["start_members"] = current
        await _save_start_members(item["id"], current)
        baseline = current

    live = max(0, current - baseline)
    peak = item.get("peak_members") or 0
    if live > peak:
        item["peak_members"] = live
        await _save_peak_members(item["id"], live)
        return live
    return peak


async def fetch_member_counts(bot, items: list, force: bool = False) -> dict:
    counts = await asyncio.gather(*(fetch_member_count(bot, it, force=force) for it in items))
    return {it["id"]: c for it, c in zip(items, counts)}


def _scope_tag(item: dict, viewer_group_id: int) -> str:
    if item.get("group_id", 0) == GLOBAL_SCOPE and viewer_group_id != GLOBAL_SCOPE:
        return "  🌐"
    return ""


def build_list_text(items: list, counts: dict, group_id: int, header: str = "یکی از موارد زیر را برای مدیریت انتخاب کنید:") -> str:
    lines = []
    for it in items:
        icon = "⛔️" if item_is_expired(it) else KIND_ICON.get(it.get("kind", "channel"), "📢")
        lines.append(
            f"{icon} {html.escape(it['title'])}{_scope_tag(it, group_id)}  •  👥 {format_quota(it, counts.get(it['id']))}"
        )
    body = "\n".join(lines)
    return f"{header}\n\n{body}" if body else header


def build_list_keyboard(items: list, group_id: int, counts: Optional[dict] = None) -> InlineKeyboardMarkup:
    rows = []
    for it in items:
        icon = "⛔️" if item_is_expired(it) else KIND_ICON.get(it.get("kind", "channel"), "📢")
        suffix = f"  •  👥 {format_quota(it, counts.get(it['id']))}" if counts is not None else ""
        rows.append(
            [InlineKeyboardButton(f"{icon} {it['title']}{_scope_tag(it, group_id)}{suffix}", callback_data=f"ch_view_{it['id']}", style="primary")]
        )
    rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="menu_channels")])
    return InlineKeyboardMarkup(rows)


def build_item_manage_keyboard(item: dict, count: Optional[int] = None) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton("⚡ تنظیم هم اکنون", callback_data=f"ch_now_{item['id']}", style="success"),
            InlineKeyboardButton("⏰ تنظیم زمان", callback_data=f"ch_time_{item['id']}", style="primary"),
        ],
        [InlineKeyboardButton("✏️ تغییر لینک", callback_data=f"ch_editlink_{item['id']}", style="primary")],
        [InlineKeyboardButton(f"👥 {format_quota(item, count)}", callback_data=f"ch_count_{item['id']}", style="primary")],
        [InlineKeyboardButton("🎯 تعرفه‌ی ممبر", callback_data=f"ch_quota_{item['id']}", style="primary")],
        [InlineKeyboardButton("🗑 حذف", callback_data=f"ch_del_{item['id']}", style="danger")],
        [InlineKeyboardButton("🔙 بازگشت به لیست", callback_data="ch_list")],
    ]
    return InlineKeyboardMarkup(rows)


def _can_manage_group(group: Optional[dict], user_id: int) -> bool:
    if group is None:
        return False
    return is_super_owner(user_id) or group.get("owner_user_id") == user_id


async def _my_groups_kb(user_id: int) -> InlineKeyboardMarkup:
    groups = await get_groups_by_owner(user_id)
    rows = [
        [InlineKeyboardButton(f"👥 {g.get('title') or g['group_id']}", callback_data=f"grp_open_{g['group_id']}")]
        for g in groups
    ]
    rows.append([InlineKeyboardButton("➕ ثبت گروه جدید", callback_data="grp_register", style="success")])
    if is_super_owner(user_id):
        rows.append([InlineKeyboardButton("🌐 آیتم‌های سراسری", callback_data="grp_global", style="primary")])
    return InlineKeyboardMarkup(rows)


async def _send_home(update_or_query, user_id: int, edit: bool) -> None:
    groups = await get_groups_by_owner(user_id)
    kb = await _my_groups_kb(user_id)
    if groups:
        text = f"👋 به «{BOT_DISPLAY_NAME}» خوش آمدید.\n\nگروه‌هایی که ثبت کرده‌اید:"
    else:
        text = (
            f"👋 به «{BOT_DISPLAY_NAME}» خوش آمدید — ربات رایگان و عمومیِ جوین اجباری.\n\n"
            "برای شروع، ربات را در گروهتان <b>ادمین</b> کنید (با دسترسی حذف پیام)، "
            "سپس «➕ ثبت گروه جدید» را بزنید."
        )
    if edit:
        await update_or_query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
    else:
        await update_or_query.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat.type != Chat.PRIVATE:
        return
    user = update.effective_user

    if user is not None and context.bot.username:
        await record_bot_start(context.bot.username, user.id)

    ACTIVE_GROUP.pop(user.id, None)
    PENDING_ITEM_QUOTA.pop(user.id, None)
    PENDING_GROUP_REGISTER.discard(user.id)
    await _send_home(update.message, user.id, edit=False)


async def _resolve_chat_identifier(context: ContextTypes.DEFAULT_TYPE, raw: str):
    raw = raw.strip()
    try:
        if raw.lstrip("-").isdigit():
            return await context.bot.get_chat(int(raw))
        username = raw
        if username.startswith("https://t.me/"):
            username = username.split("https://t.me/", 1)[1].split("?")[0].split("/")[0]
        username = username.lstrip("@")
        return await context.bot.get_chat(f"@{username}")
    except TelegramError as exc:
        logger.info("عدم امکان resolve چت %s: %s", raw, exc)
        return None


async def owner_panel_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data
    await query.answer()

    # --- ناوبری بین گروه‌ها ---------------------------------------------------
    if data == "grp_switch" or data == "menu_main_root":
        ACTIVE_GROUP.pop(user_id, None)
        await _send_home(query, user_id, edit=True)
        return

    if data == "grp_register":
        PENDING_GROUP_REGISTER.add(user_id)
        await query.edit_message_text(
            "برای ثبت گروهتان در ربات:\n\n"
            "۱) ربات را در گروه <b>ادمین</b> کنید (دسترسی حذف پیام لازم است).\n"
            "۲) یک پیام از آن گروه <b>فوروارد</b> کنید، یا آیدی عددی گروه را بفرستید (مثل <code>-1001234567890</code>).\n\n"
            "⚠️ فقط اگر خودتان در آن گروه ادمین/مالک باشید، ثبت انجام می‌شود.",
            parse_mode=ParseMode.HTML,
            reply_markup=back_kb("grp_switch"),
        )
        return

    if data == "grp_global":
        if not is_super_owner(user_id):
            await query.answer("فقط مالک اصلی ربات به این بخش دسترسی دارد.", show_alert=True)
            return
        ACTIVE_GROUP[user_id] = GLOBAL_SCOPE
        await query.edit_message_text(
            "🌐 مدیریت آیتم‌های سراسری — هر آیتمی اینجا اضافه شود، در <b>همه‌ی گروه‌های ثبت‌شده</b> روی ربات جوین اجباری می‌شود.",
            parse_mode=ParseMode.HTML,
            reply_markup=group_menu_kb(GLOBAL_SCOPE),
        )
        return

    if data.startswith("grp_open_"):
        group_id = int(data.split("_")[-1])
        group = await get_group(group_id)
        if not _can_manage_group(group, user_id):
            await query.answer("شما دسترسی مدیریت این گروه را ندارید.", show_alert=True)
            return
        ACTIVE_GROUP[user_id] = group_id
        await query.edit_message_text(
            f"مدیریت گروه: <b>{html.escape(group.get('title') or str(group_id))}</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=group_menu_kb(group_id),
        )
        return

    if data == "grp_unregister":
        group_id = ACTIVE_GROUP.get(user_id)
        group = await get_group(group_id) if group_id is not None else None
        if not _can_manage_group(group, user_id) or group_id == GLOBAL_SCOPE:
            await query.answer("دسترسی ندارید.", show_alert=True)
            return
        await unregister_group(group_id)
        ACTIVE_GROUP.pop(user_id, None)
        await query.edit_message_text("گروه و تمام آیتم‌های مخصوص آن حذف شد ✅")
        await _send_home(query.message, user_id, edit=False)
        return

    # --- از اینجا به بعد: عملیات روی گروهِ فعال کاربر ---------------------------
    group_id = ACTIVE_GROUP.get(user_id)
    if group_id is None:
        await _send_home(query, user_id, edit=True)
        return
    group = await get_group(group_id) if group_id != GLOBAL_SCOPE else {"group_id": GLOBAL_SCOPE, "owner_user_id": SUPER_OWNER_ID}
    if not _can_manage_group(group, user_id):
        ACTIVE_GROUP.pop(user_id, None)
        await query.answer("دسترسی به این گروه ندارید.", show_alert=True)
        return

    if not data.startswith("ch_time_"):
        PENDING_ITEM_TIME.pop(user_id, None)
    if not data.startswith("ch_quota_"):
        PENDING_ITEM_QUOTA.pop(user_id, None)

    if data == "menu_main":
        title = html.escape(group.get("title") or str(group_id)) if group_id != GLOBAL_SCOPE else "🌐 سراسری"
        await query.edit_message_text(
            f"مدیریت گروه: <b>{title}</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=group_menu_kb(group_id),
        )

    elif data == "menu_channels":
        await query.edit_message_text("مدیریت آیتم‌های جوین اجباری:", reply_markup=CHANNELS_MENU)

    elif data == "ch_add":
        PENDING_ITEM_ADD.add(user_id)
        await query.edit_message_text(
            "برای افزودن <b>کانال</b> یا <b>گروه</b> (ربات باید ادمین آن باشد)، یکی از راه‌های زیر:\n\n"
            "۱) فوروارد یک پیام از آن کانال/گروه\n"
            "۲) ارسال مستقیم یوزرنیم: <code>@channel_username</code>\n"
            "۳) ارسال مستقیم لینک عمومی: <code>https://t.me/channel_username</code>\n"
            "۴) ارسال مستقیم آیدی عددی (اگر ربات از قبل عضو/ادمین آن است): <code>-1001234567890</code>\n\n"
            "برای کانال/گروه <b>خصوصی</b> که فقط لینک دعوت (+…) دارید، لطفاً فوروارد کنید؛ "
            "یا اگر آیدی عددی را می‌دانید:\n"
            "<code>-1001234567890 | https://t.me/+AbCdEfGhIj</code>\n\n"
            "اگر لینک ندارید ولی ربات ادمین است، فقط یوزرنیم/آیدی/فوروارد کافیست؛ لینک خودکار ساخته می‌شود.",
            parse_mode=ParseMode.HTML,
            reply_markup=back_kb("menu_channels"),
        )

    elif data == "ch_add_bot":
        PENDING_BOT_ADD.add(user_id)
        await query.edit_message_text(
            "یکی از این‌ها را ارسال کنید:\n\n"
            "۱) یوزرنیم ربات: <code>@id_bot</code>\n"
            "۲) لینک ربات: <code>https://t.me/id_bot</code>\n"
            "۳) لینک دعوت با پارامتر استارت: <code>https://t.me/id_bot?start=ref123</code>\n\n"
            "دکمه‌ی این ربات یک لینک مستقیم است و کاربر با زدن آن به پیوی ربات هدایت می‌شود. "
            "ورودش وقتی تایید می‌شود که «بررسی عضویت» را بزند.",
            parse_mode=ParseMode.HTML,
            reply_markup=back_kb("menu_channels"),
        )

    elif data == "ch_list":
        items = await list_all_items(group_id)
        if not items:
            await query.edit_message_text("هیچ آیتمی ثبت نشده است.", reply_markup=back_kb("menu_channels"))
        else:
            counts = await fetch_member_counts(context.bot, items, force=True)
            await query.edit_message_text(
                build_list_text(items, counts, group_id),
                parse_mode=ParseMode.HTML,
                reply_markup=build_list_keyboard(items, group_id, counts),
            )

    elif data.startswith("ch_view_"):
        item_id = int(data.split("_")[-1])
        item = await get_item(group_id, item_id)
        if not item:
            await query.edit_message_text("این آیتم دیگر وجود ندارد.", reply_markup=back_kb("ch_list"))
        elif item.get("group_id", 0) == GLOBAL_SCOPE and group_id != GLOBAL_SCOPE:
            await query.answer("این آیتم سراسری است؛ فقط مالک اصلی ربات می‌تواند آن را ویرایش کند.", show_alert=True)
        else:
            label = KIND_LABEL.get(item.get("kind", "channel"), "کانال")
            text = (
                f"مدیریت {label}: <b>{html.escape(item['title'])}</b>\n"
                f"شناسه: <code>{item['chat_id']}</code>\n"
                f"لینک: {item['invite_link']}\n"
                f"وضعیت: {describe_item_schedule(item)}"
            )
            count = await fetch_member_count(context.bot, item)
            text += f"\nتعداد ورودی‌ها: {format_quota(item, count)}"
            await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=build_item_manage_keyboard(item, count))

    elif data.startswith("ch_editlink_"):
        item_id = int(data.split("_")[-1])
        PENDING_LINK_EDIT[user_id] = item_id
        await query.edit_message_text("لینک جدید را ارسال کنید:", reply_markup=back_kb(f"ch_view_{item_id}"))

    elif data.startswith("ch_count_"):
        item_id = int(data.split("_")[-1])
        item = await get_item(group_id, item_id)
        if not item:
            await query.edit_message_text("این آیتم دیگر وجود ندارد.", reply_markup=back_kb("ch_list"))
            return
        count = await fetch_member_count(context.bot, item, force=True)
        try:
            await query.edit_message_reply_markup(reply_markup=build_item_manage_keyboard(item, count))
        except BadRequest as exc:
            if "not modified" not in str(exc).lower():
                raise

    elif data.startswith("ch_quota_"):
        item_id = int(data.split("_")[-1])
        item = await get_item(group_id, item_id)
        if not item:
            await query.edit_message_text("این آیتم دیگر وجود ندارد.", reply_markup=back_kb("ch_list"))
            return
        PENDING_ITEM_QUOTA[user_id] = (item_id, False)
        await query.edit_message_text(
            QUOTA_PROMPT.format(title=html.escape(item["title"])),
            parse_mode=ParseMode.HTML,
            reply_markup=back_kb(f"ch_view_{item_id}"),
        )

    elif data.startswith("ch_now_"):
        item_id = int(data.split("_")[-1])
        item = await get_item(group_id, item_id)
        if not item:
            await query.edit_message_text("این آیتم دیگر وجود ندارد.", reply_markup=back_kb("ch_list"))
            return
        PENDING_ITEM_TIME.pop(user_id, None)
        err = await set_item_expiry(item_id, None)
        if err:
            await query.edit_message_text(f"❌ ذخیره نشد:\n{err}", reply_markup=back_kb(f"ch_view_{item_id}"))
            return
        if item.get("quota_done"):
            await query.edit_message_text(
                f"تعرفه‌ی ممبرِ «{item['title']}» قبلاً کامل شده است. برای فعال‌سازی دوباره، "
                "از دکمه‌ی «🎯 تعرفه‌ی ممبر» تعداد جدید را ثبت کنید.",
                reply_markup=back_kb(f"ch_view_{item_id}"),
            )
            return
        await query.edit_message_text(f"«{item['title']}» هم‌اکنون فعال شد و محدودیت زمانی ندارد ✅", reply_markup=CHANNELS_MENU)

    elif data.startswith("ch_time_"):
        item_id = int(data.split("_")[-1])
        item = await get_item(group_id, item_id)
        if not item:
            await query.edit_message_text("این آیتم دیگر وجود ندارد.", reply_markup=back_kb("ch_list"))
            return
        PENDING_ITEM_TIME[user_id] = item_id
        await query.edit_message_text(
            f"مدت فعال بودن جوین اجباریِ «{item['title']}» را بفرستید. بعد از این مدت، این مورد خودکار از جوین اجباری کنار می‌رود.\n\n"
            "مثال‌ها: <code>30m</code> (دقیقه) ، <code>12h</code> (ساعت) ، <code>7d</code> (روز) ، "
            "<code>90 دقیقه</code> ، <code>2 روز</code>\n"
            "فقط عدد = ساعت.",
            parse_mode=ParseMode.HTML,
            reply_markup=back_kb(f"ch_view_{item_id}"),
        )

    elif data.startswith("ch_del_"):
        item_id = int(data.split("_")[-1])
        removed = await remove_item_by_id(item_id)
        items = await list_all_items(group_id)
        msg = "حذف شد ✅" if removed else "حذف نشد، دوباره تلاش کنید."
        if items:
            counts = await fetch_member_counts(context.bot, items)
            await query.edit_message_text(
                build_list_text(items, counts, group_id, header=f"{msg}\n\nیکی از موارد زیر را برای مدیریت انتخاب کنید:"),
                parse_mode=ParseMode.HTML,
                reply_markup=build_list_keyboard(items, group_id, counts),
            )
        else:
            await query.edit_message_text(f"{msg}\n\nهیچ آیتمی ثبت نشده است.", reply_markup=back_kb("menu_channels"))

    elif data == "menu_texts":
        await query.edit_message_text("ویرایش متن‌ها:", reply_markup=TEXTS_MENU)

    elif data == "txt_warn":
        PENDING_TEXT_EDIT[user_id] = "warn_text"
        current = await get_text(group_id, "warn_text", DEFAULT_WARN_TEXT)
        await query.edit_message_text(
            "متن فعلی هشدار عضویت (لیست موارد باقی‌مانده خودکار زیرش، داخل نقل قول، اضافه می‌شود):\n\n"
            f"{html.escape(current)}\n\n"
            "متن جدید را با همان قالب‌بندی دلخواه بفرستید. متغیرها: <code>{mention}</code> یا <code>منشن_کاربر</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=back_kb("menu_texts"),
        )

    elif data == "txt_joined":
        PENDING_TEXT_EDIT[user_id] = "joined_text"
        current = await get_text(group_id, "joined_text", DEFAULT_JOINED_TEXT)
        await query.edit_message_text(
            "متن فعلی تایید عضویت:\n\n"
            f"{html.escape(current)}\n\n"
            "متن جدید را با همان قالب‌بندی دلخواه بفرستید. متغیرها: <code>{mention}</code> یا <code>منشن_کاربر</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=back_kb("menu_texts"),
        )

    elif data == "menu_delete_timer":
        current = await get_warn_delete_seconds(group_id)
        PENDING_DELETE_TIMER_SET.add(user_id)
        await query.edit_message_text(
            f"زمان فعلی حذف خودکار پیام هشدار: <b>{current:g} ثانیه</b>\n\n"
            "عدد جدید (ثانیه) را بفرستید. برای غیرفعال‌کردن حذف خودکار، <code>0</code> بفرستید.",
            parse_mode=ParseMode.HTML,
            reply_markup=back_kb("menu_main"),
        )

    elif data == "menu_status":
        items = await list_all_items(group_id)
        active_count = len([it for it in items if not item_is_expired(it)])
        delay = await get_warn_delete_seconds(group_id)
        text = (
            f"وضعیت گروه «{html.escape(group.get('title') or str(group_id))}»:\n\n"
            f"شناسه گروه: <code>{group_id}</code>\n"
            f"تعداد کل آیتم‌ها: {len(items)}\n"
            f"آیتم‌های فعال: {active_count}\n"
            f"زمان حذف پیام هشدار: {delay:g} ثانیه"
        )
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=back_kb("menu_main"))


QUOTA_PROMPT = (
    "تعداد ورودی مورد نیاز برای «{title}» را بفرستید (فقط عدد، مثل <code>500</code>).\n"
    "برای نامحدودکردن، <code>0</code> بفرستید."
)


async def owner_private_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return

    user_id = user.id

    # --- ثبت گروه جدید (در دسترس همه، نه فقط گروه فعال) -----------------------
    if user_id in PENDING_GROUP_REGISTER:
        raw = None
        if message.forward_origin and getattr(message.forward_origin, "chat", None):
            raw = str(message.forward_origin.chat.id)
        elif message.text:
            raw = message.text.strip()
        if not raw:
            await message.reply_text("لطفاً یک پیام از گروه فوروارد کنید یا آیدی عددی گروه را بفرستید.")
            return

        try:
            target_chat_id = int(raw)
        except ValueError:
            chat = await _resolve_chat_identifier(context, raw)
            target_chat_id = chat.id if chat else None

        if target_chat_id is None:
            await message.reply_text("چت پیدا نشد. مطمئن شوید آیدی درست است یا پیام را مستقیم از گروه فوروارد کنید.")
            return

        try:
            target_chat = await context.bot.get_chat(target_chat_id)
        except TelegramError as exc:
            await message.reply_text(f"❌ ربات به این گروه دسترسی ندارد: {exc}")
            return

        if target_chat.type not in (Chat.GROUP, Chat.SUPERGROUP):
            await message.reply_text("فقط گروه (نه کانال) قابل ثبت است.")
            return

        existing = await get_group(target_chat_id)
        if existing and existing.get("owner_user_id") not in (user_id, None) and not is_super_owner(user_id):
            await message.reply_text("این گروه قبلاً توسط کاربر دیگری در ربات ثبت شده است.")
            return

        try:
            requester_member = await context.bot.get_chat_member(target_chat_id, user_id)
        except TelegramError as exc:
            await message.reply_text(f"❌ بررسی عضویت شما در گروه ممکن نشد: {exc}")
            return
        if requester_member.status not in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER) and not is_super_owner(user_id):
            await message.reply_text("فقط ادمین یا مالک گروه می‌تواند آن را در ربات ثبت کند.")
            return

        try:
            bot_member = await context.bot.get_chat_member(target_chat_id, context.bot.id)
        except TelegramError as exc:
            await message.reply_text(f"❌ بررسی عضویت ربات در گروه ممکن نشد: {exc}")
            return
        if bot_member.status != ChatMemberStatus.ADMINISTRATOR:
            await message.reply_text("ابتدا ربات را در گروه <b>ادمین</b> کنید (دسترسی حذف پیام)، سپس دوباره تلاش کنید.", parse_mode=ParseMode.HTML)
            return

        err = await register_group(target_chat_id, user_id, target_chat.title or str(target_chat_id))
        PENDING_GROUP_REGISTER.discard(user_id)
        if err:
            await message.reply_text(f"❌ ثبت نشد:\n{err}")
            return
        ACTIVE_GROUP[user_id] = target_chat_id
        await message.reply_text(
            f"گروه «{target_chat.title}» ثبت شد ✅\nحالا می‌توانید جوین اجباری‌های خودتان را برایش تعریف کنید.",
            reply_markup=group_menu_kb(target_chat_id),
        )
        return

    # --- از اینجا به بعد: نیاز به یک گروه فعال در پنل -------------------------
    group_id = ACTIVE_GROUP.get(user_id)
    if group_id is None:
        return  # پیام در پیوی بدون زمینه‌ی پنل: نادیده گرفته می‌شود
    group = await get_group(group_id) if group_id != GLOBAL_SCOPE else {"group_id": GLOBAL_SCOPE, "owner_user_id": SUPER_OWNER_ID}
    if not _can_manage_group(group, user_id):
        ACTIVE_GROUP.pop(user_id, None)
        return

    if user_id in PENDING_DELETE_TIMER_SET:
        PENDING_DELETE_TIMER_SET.discard(user_id)
        text = (message.text or "").translate(_PERSIAN_DIGITS).strip()
        try:
            seconds = float(text)
            if seconds < 0 or seconds > 3600:
                raise ValueError
        except ValueError:
            await message.reply_text("عدد نامعتبر است (بین ۰ تا ۳۶۰۰ ثانیه).")
            return
        err = await set_warn_delete_seconds(group_id, seconds)
        if err:
            await message.reply_text(f"❌ ذخیره نشد:\n{err}")
        else:
            await message.reply_text(f"زمان حذف خودکار روی {seconds:g} ثانیه تنظیم شد ✅", reply_markup=group_menu_kb(group_id))
        return

    if user_id in PENDING_TEXT_EDIT:
        key = PENDING_TEXT_EDIT.pop(user_id)
        if not message.text:
            await message.reply_text("لطفاً یک متن بفرستید.")
            PENDING_TEXT_EDIT[user_id] = key
            return
        err = await set_text(group_id, key, message.html_text or message.text)
        if err:
            await message.reply_text(f"❌ ذخیره نشد:\n{err}")
        else:
            await message.reply_text("متن ذخیره شد ✅", reply_markup=TEXTS_MENU)
        return

    if user_id in PENDING_LINK_EDIT:
        item_id = PENDING_LINK_EDIT.pop(user_id)
        if not message.text:
            await message.reply_text("لطفاً لینک را بفرستید.")
            PENDING_LINK_EDIT[user_id] = item_id
            return
        err = await update_item_link(item_id, message.text.strip())
        if err:
            await message.reply_text(f"❌ ذخیره نشد:\n{err}")
        else:
            await message.reply_text("لینک به‌روزرسانی شد ✅", reply_markup=back_kb(f"ch_view_{item_id}"))
        return

    if user_id in PENDING_ITEM_TIME:
        item_id = PENDING_ITEM_TIME[user_id]
        if not message.text:
            await message.reply_text("لطفاً مدت زمان را بفرستید.")
            return
        delta = parse_duration(message.text)
        if delta is None:
            await message.reply_text("فرمت نامعتبر است. مثال: 30m، 12h، 7d، 90 دقیقه، 2 روز")
            return
        PENDING_ITEM_TIME.pop(user_id, None)
        expires_at = datetime.now(timezone.utc) + delta
        err = await set_item_expiry(item_id, expires_at)
        if err:
            await message.reply_text(f"❌ ذخیره نشد:\n{err}")
        else:
            await message.reply_text(
                f"جوین اجباری به مدت {format_duration(delta)} فعال شد ✅",
                reply_markup=back_kb(f"ch_view_{item_id}"),
            )
        return

    if user_id in PENDING_ITEM_QUOTA:
        item_id, _just_added = PENDING_ITEM_QUOTA[user_id]
        text = (message.text or "").translate(_PERSIAN_DIGITS).strip()
        if not text.isdigit():
            await message.reply_text("لطفاً فقط عدد بفرستید.")
            return
        limit = min(int(text), MAX_MEMBER_LIMIT)
        PENDING_ITEM_QUOTA.pop(user_id, None)
        item = await get_item(group_id, item_id)
        baseline = None
        if item and limit > 0:
            baseline = await fetch_member_count(context.bot, item, force=True)
        err = await set_item_quota(item_id, limit, baseline)
        if err:
            await message.reply_text(f"❌ ذخیره نشد:\n{err}")
        else:
            msg = "تعرفه‌ی ممبر نامحدود شد ✅" if limit == 0 else f"تعرفه‌ی ممبر روی {limit:,} تنظیم شد ✅"
            await message.reply_text(msg, reply_markup=back_kb(f"ch_view_{item_id}"))
        return

    if user_id in PENDING_ITEM_ADD or user_id in PENDING_BOT_ADD:
        is_bot_item = user_id in PENDING_BOT_ADD

        if is_bot_item:
            raw = message.text.strip() if message.text else None
            if not raw:
                await message.reply_text("لطفاً یوزرنیم یا لینک ربات را بفرستید.")
                return
            username = raw
            start_param = None
            if "t.me/" in username:
                username = username.split("t.me/", 1)[1]
                if "?start=" in username:
                    username, start_param = username.split("?start=", 1)
            username = username.lstrip("@").strip("/")
            if not username:
                await message.reply_text("فرمت نامعتبر است.")
                return
            link = f"https://t.me/{username}" + (f"?start={start_param}" if start_param else "")
            err = await add_item("bot", username, f"@{username}", link, group_id, user_id)
            PENDING_BOT_ADD.discard(user_id)
            if err:
                await message.reply_text(f"❌ ذخیره نشد:\n{err}")
            else:
                await message.reply_text(f"ربات @{username} اضافه شد ✅", reply_markup=CHANNELS_MENU)
            return

        chat = None
        manual_link = None
        if message.forward_origin and getattr(message.forward_origin, "chat", None):
            chat = message.forward_origin.chat
        elif message.text:
            raw = message.text.strip()
            if "|" in raw:
                left, manual_link = (p.strip() for p in raw.split("|", 1))
                raw = left
            chat = await _resolve_chat_identifier(context, raw)

        if chat is None:
            await message.reply_text("چت پیدا نشد. فوروارد کنید یا یوزرنیم/آیدی/لینک معتبر بفرستید.")
            return
        if chat.type not in (Chat.CHANNEL, Chat.GROUP, Chat.SUPERGROUP):
            await message.reply_text("فقط کانال یا گروه قابل افزودن است.")
            return

        kind = "channel" if chat.type == Chat.CHANNEL else "group"
        invite_link = manual_link
        if not invite_link:
            if chat.username:
                invite_link = f"https://t.me/{chat.username}"
            else:
                try:
                    link_obj = await context.bot.create_chat_invite_link(chat.id)
                    invite_link = link_obj.invite_link
                except TelegramError as exc:
                    await message.reply_text(
                        f"❌ لینک دعوت خودکار ساخته نشد (ربات باید ادمین با دسترسی دعوت باشد): {exc}\n"
                        "می‌توانید دوباره بفرستید و لینک را دستی اضافه کنید: <code>chat_id | link</code>",
                        parse_mode=ParseMode.HTML,
                    )
                    return

        try:
            start_members = await context.bot.get_chat_member_count(chat.id)
        except TelegramError:
            start_members = None

        err = await add_item(kind, str(chat.id), chat.title or str(chat.id), invite_link, group_id, user_id, start_members)
        PENDING_ITEM_ADD.discard(user_id)
        if err:
            await message.reply_text(f"❌ ذخیره نشد:\n{err}")
            return
        items = await list_all_items(group_id)
        new_item = next((it for it in items if str(it["chat_id"]) == str(chat.id) and it.get("group_id") == group_id), None)
        if new_item:
            await message.reply_text(
                f"«{chat.title}» اضافه شد ✅\nبرای فعال‌سازی زمان‌بندی:",
                reply_markup=build_schedule_keyboard(new_item["id"]),
            )
        else:
            await message.reply_text(f"«{chat.title}» اضافه شد ✅", reply_markup=CHANNELS_MENU)
        return


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    if isinstance(context.error, Conflict):
        logger.error(
            "خطای Conflict: یک نمونه‌ی دیگر از همین ربات (همین توکن) هم‌زمان در حال polling است. "
            "مطمئن شوید فقط یک instance از سرویس روی Render (یا هر جای دیگر) در حال اجراست "
            "و دیپلوی قبلی کاملاً متوقف شده."
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
    global _quota_bot
    application: Application = app["application"]
    await application.initialize()
    await application.start()
    _quota_bot = application.bot

    webhook_url = f"{BASE_URL}{WEBHOOK_PATH}"
    await application.bot.set_webhook(
        url=webhook_url,
        secret_token=WEBHOOK_SECRET,
        allowed_updates=Update.ALL_TYPES,
        max_connections=100,
        drop_pending_updates=False,
    )
    logger.info("وبهوک روی %s تنظیم شد", webhook_url)


async def _on_cleanup(app: web.Application) -> None:
    application: Application = app["application"]
    await application.bot.delete_webhook()
    await application.stop()
    await application.shutdown()


def main() -> None:
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError("متغیرهای محیطی SUPABASE_URL و SUPABASE_KEY باید تنظیم شوند.")
    if not BASE_URL:
        raise RuntimeError(
            "آدرس عمومی سرویس پیدا نشد. اگر روی Render نیستید، متغیر محیطی "
            "WEBHOOK_URL را برابر آدرس عمومی سرویس‌تان (بدون / انتهایی) ست کنید."
        )

    request = HTTPXRequest(
        connect_timeout=15.0,
        read_timeout=30.0,
        write_timeout=15.0,
        pool_timeout=15.0,
    )

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

    application.add_handler(CallbackQueryHandler(on_check_membership, pattern=r"^check_membership(_\d+)?$"))
    application.add_handler(CallbackQueryHandler(owner_panel_router, pattern="^(menu_|ch_|txt_|grp_)"))

    application.add_handler(
        MessageHandler(filters.ChatType.GROUPS & ~filters.StatusUpdate.ALL, on_group_message)
    )
    application.add_handler(
        MessageHandler(filters.ChatType.PRIVATE & filters.ALL, owner_private_message)
    )

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


def _log_task_exception(task: asyncio.Task) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error("خطای پردازش‌نشده در تسک آپدیت: %s", exc, exc_info=exc)


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


if __name__ == "__main__":
    main()
