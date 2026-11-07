"""کیبوردها — aiogram 3"""
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder


def main_menu() -> ReplyKeyboardMarkup:
    b = ReplyKeyboardBuilder()
    b.row(KeyboardButton(text="➕ افزودن اکانت"),  KeyboardButton(text="📊 وضعیت زنده"))
    b.row(KeyboardButton(text="👥 مدیریت اکانت‌ها"), KeyboardButton(text="📈 آمار پیشرفته"))
    b.row(KeyboardButton(text="🎬 روشن/خاموش ویو"),  KeyboardButton(text="🔄 چرخش دستی"))
    b.row(KeyboardButton(text="⚙️ تنظیمات"),          KeyboardButton(text="📢 کانال هدف"))
    b.row(KeyboardButton(text="❓ راهنما"))
    return b.as_markup(resize_keyboard=True)


def view_toggle_menu(current_paused: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if current_paused:
        b.button(text="▶️ روشن کردن ویو",  callback_data="view:resume")
    else:
        b.button(text="⏸️  توقف ویو",       callback_data="view:pause")
    b.button(text="🔄 بروزرسانی وضعیت",    callback_data="view:refresh")
    b.button(text="🔙 برگشت",               callback_data="menu:main")
    b.adjust(1)
    return b.as_markup()


def status_menu() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🟢 آنلاین",         callback_data="status:online")
    b.button(text="💤 idle",           callback_data="status:idle")
    b.button(text="🔴 خطا",            callback_data="status:error")
    b.button(text="🟡 Flood",          callback_data="status:flood")
    b.button(text="📊 کل",             callback_data="status:all")
    b.button(text="🔙 برگشت",          callback_data="menu:main")
    b.button(text="🔄 بروزرسانی زنده", callback_data="status:refresh")
    b.adjust(3, 3, 1)
    return b.as_markup()


def accounts_menu() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="📋 لیست کامل",   callback_data="acc:list:0")
    b.button(text="➕ افزودن جدید", callback_data="acc:add")
    b.button(text="🔄 چرخش فوری",  callback_data="acc:rotate")
    b.button(text="🧹 حذف flood‌ها",callback_data="acc:cleanup")
    b.button(text="📥 بکاپ الان",   callback_data="acc:backup")
    b.button(text="🔙 برگشت",       callback_data="menu:main")
    b.adjust(2)
    return b.as_markup()


def accounts_list_kb(accounts: list, page: int = 0, per_page: int = 10) -> InlineKeyboardMarkup:
    b   = InlineKeyboardBuilder()
    s   = page * per_page
    e   = s + per_page
    tot = (len(accounts) + per_page - 1) // per_page

    for a in accounts[s:e]:
        icon = {"online": "🟢", "flood": "🟡", "error": "🔴",
                "idle": "💤", "dead": "⚫"}.get(a.get("status", "idle"), "⚪")
        shift_icon = "🅰️" if a.get("shift") == "A" else "🅱️"
        b.button(text=f"{icon} {shift_icon} {a['phone']}",
                 callback_data=f"acc:info:{a['id']}")
    b.adjust(1)

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️ قبلی",     callback_data=f"acc:list:{page-1}"))
    nav.append(    InlineKeyboardButton(text=f"📄 {page+1}/{tot}", callback_data="acc:noop"))
    if e < len(accounts):
        nav.append(InlineKeyboardButton(text="بعدی ➡️",     callback_data=f"acc:list:{page+1}"))

    b.row(*nav)
    b.row(
        InlineKeyboardButton(text="🔄 رفرش",   callback_data=f"acc:list:{page}"),
        InlineKeyboardButton(text="🔙 برگشت",  callback_data="menu:accounts"),
    )
    return b.as_markup()


def stats_menu() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="📊 آمار کلی",       callback_data="stats:general")
    b.button(text="📈 آمار ۲۴ ساعت",   callback_data="stats:daily")
    b.button(text="🌐 وضعیت WARP",     callback_data="stats:warp")
    b.button(text="🔄 چرخه شیفت",      callback_data="stats:shift")
    b.button(text="📉 نمودار موفقیت",  callback_data="stats:chart")
    b.button(text="🔙 برگشت",          callback_data="menu:main")
    b.adjust(2)
    return b.as_markup()


def settings_menu() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="⏱️ طول شیفت",     callback_data="set:shift")
    b.button(text="👥 تعداد فعال",   callback_data="set:active")
    b.button(text="🛡️ وضعیت نگهبان",callback_data="set:guardian")
    b.button(text="💾 بکاپ",         callback_data="set:backup")
    b.button(text="📊 WARP",         callback_data="set:warp")
    b.button(text="🔙 برگشت",        callback_data="menu:main")
    b.adjust(2)
    return b.as_markup()


def channel_menu() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="👥 عضویت همه اکانت‌ها", callback_data="ch:join")
    b.button(text="📊 چک عضویت‌ها",         callback_data="ch:check")
    b.button(text="📢 نمایش کانال فعلی",    callback_data="ch:info")
    b.button(text="🔙 برگشت",               callback_data="menu:main")
    b.adjust(1)
    return b.as_markup()


def confirm_menu(action: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅ بله", callback_data=f"cfm:yes:{action}")
    b.button(text="❌ خیر", callback_data=f"cfm:no:{action}")
    b.adjust(2)
    return b.as_markup()


def cancel_menu() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="❌ انصراف", callback_data="add:cancel")
    return b.as_markup()
