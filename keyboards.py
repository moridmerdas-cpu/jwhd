"""کیبوردها — aiogram 3.x"""
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
)


def main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ افزودن اکانت"),  KeyboardButton(text="📊 وضعیت زنده")],
            [KeyboardButton(text="👥 مدیریت اکانت‌ها"), KeyboardButton(text="📈 آمار پیشرفته")],
            [KeyboardButton(text="🎬 روشن/خاموش ویو"),  KeyboardButton(text="🔄 چرخش دستی")],
            [KeyboardButton(text="⚙️ تنظیمات"),         KeyboardButton(text="📢 کانال هدف")],
            [KeyboardButton(text="❓ راهنما")],
        ],
        resize_keyboard=True,
    )


def view_toggle_menu(current_paused: bool):
    rows = []
    if current_paused:
        rows.append([InlineKeyboardButton(text="▶️ روشن کردن ویو", callback_data="view:resume")])
    else:
        rows.append([InlineKeyboardButton(text="⏸️ توقف ویو", callback_data="view:pause")])
    rows.append([InlineKeyboardButton(text="🔄 بروزرسانی وضعیت", callback_data="view:refresh")])
    rows.append([InlineKeyboardButton(text="🔙 برگشت", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def status_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🟢 آنلاین",  callback_data="status:online"),
            InlineKeyboardButton(text="💤 idle",    callback_data="status:idle"),
            InlineKeyboardButton(text="🔴 خطا",    callback_data="status:error"),
        ],
        [
            InlineKeyboardButton(text="🟡 Flood",   callback_data="status:flood"),
            InlineKeyboardButton(text="📊 کل",      callback_data="status:all"),
            InlineKeyboardButton(text="🔙 برگشت",   callback_data="menu:main"),
        ],
        [InlineKeyboardButton(text="🔄 بروزرسانی زنده", callback_data="status:refresh")],
    ])


def accounts_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📋 لیست کامل",   callback_data="acc:list:0"),
            InlineKeyboardButton(text="➕ افزودن جدید",  callback_data="acc:add"),
        ],
        [
            InlineKeyboardButton(text="🔄 چرخش فوری",   callback_data="acc:rotate"),
            InlineKeyboardButton(text="🧹 حذف flood‌ها", callback_data="acc:cleanup"),
        ],
        [
            InlineKeyboardButton(text="📥 بکاپ الان",   callback_data="acc:backup"),
            InlineKeyboardButton(text="🔙 برگشت",        callback_data="menu:main"),
        ],
    ])


def accounts_list_kb(accounts, page=0, per_page=10):
    s = page * per_page
    e = s + per_page
    total_pages = max(1, (len(accounts) + per_page - 1) // per_page)
    rows = []
    for a in accounts[s:e]:
        icon = {"online": "🟢", "flood": "🟡", "error": "🔴",
                "idle": "💤", "dead": "⚫"}.get(a.get("status", "idle"), "⚪")
        shift_icon = "🅰️" if a.get("shift") == "A" else "🅱️"
        rows.append([InlineKeyboardButton(
            text=f"{icon} {shift_icon} {a['phone']}",
            callback_data=f"acc:info:{a['id']}"
        )])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️ قبلی", callback_data=f"acc:list:{page-1}"))
    nav.append(InlineKeyboardButton(text=f"📄 {page+1}/{total_pages}", callback_data="acc:noop"))
    if e < len(accounts):
        nav.append(InlineKeyboardButton(text="بعدی ➡️", callback_data=f"acc:list:{page+1}"))
    if nav:
        rows.append(nav)
    rows.append([
        InlineKeyboardButton(text="🔄 رفرش",    callback_data=f"acc:list:{page}"),
        InlineKeyboardButton(text="🔙 برگشت",   callback_data="menu:accounts"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def stats_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📊 آمار کلی",      callback_data="stats:general"),
            InlineKeyboardButton(text="📈 آمار ۲۴ ساعت",  callback_data="stats:daily"),
        ],
        [
            InlineKeyboardButton(text="🌐 وضعیت WARP",    callback_data="stats:warp"),
            InlineKeyboardButton(text="🔄 چرخه شیفت",     callback_data="stats:shift"),
        ],
        [
            InlineKeyboardButton(text="📉 نمودار موفقیت", callback_data="stats:chart"),
            InlineKeyboardButton(text="🔙 برگشت",          callback_data="menu:main"),
        ],
    ])


def settings_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⏱️ طول شیفت",     callback_data="set:shift"),
            InlineKeyboardButton(text="👥 تعداد فعال",   callback_data="set:active"),
        ],
        [
            InlineKeyboardButton(text="🛡️ وضعیت نگهبان", callback_data="set:guardian"),
            InlineKeyboardButton(text="💾 بکاپ",          callback_data="set:backup"),
        ],
        [
            InlineKeyboardButton(text="📊 WARP",          callback_data="set:warp"),
            InlineKeyboardButton(text="🔙 برگشت",         callback_data="menu:main"),
        ],
    ])


def channel_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 عضویت همه اکانت‌ها", callback_data="ch:join")],
        [InlineKeyboardButton(text="📊 چک عضویت‌ها",         callback_data="ch:check")],
        [InlineKeyboardButton(text="📢 نمایش کانال فعلی",    callback_data="ch:info")],
        [InlineKeyboardButton(text="🔙 برگشت",                callback_data="menu:main")],
    ])


def confirm_menu(action):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ بله", callback_data=f"cfm:yes:{action}"),
        InlineKeyboardButton(text="❌ خیر", callback_data=f"cfm:no:{action}"),
    ]])


def cancel_menu():
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="❌ انصراف", callback_data="add:cancel")
    ]])
