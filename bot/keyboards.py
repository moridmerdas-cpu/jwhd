"""کیبوردها — aiogram 3"""
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder


def main_menu() -> ReplyKeyboardMarkup:
    b = ReplyKeyboardBuilder()
    b.row(KeyboardButton(text="➕ افزودن اکانت"),   KeyboardButton(text="📊 وضعیت زنده"))
    b.row(KeyboardButton(text="👥 مدیریت اکانت‌ها"), KeyboardButton(text="📈 آمار پیشرفته"))
    b.row(KeyboardButton(text="🎬 روشن/خاموش ویو"),  KeyboardButton(text="🔄 چرخش دستی"))
    b.row(KeyboardButton(text="⚙️ تنظیمات"),          KeyboardButton(text="🎯 گروه هدف"))
    b.row(KeyboardButton(text="🤖 استفاده از ممبرها"), KeyboardButton(text="❓ راهنما"))
    return b.as_markup(resize_keyboard=True)


def use_members_menu() -> InlineKeyboardMarkup:
    """منوی استفاده از ممبرها"""
    b = InlineKeyboardBuilder()
    b.button(text="🚀 استارت ربات",         callback_data="mem:start_bot")
    b.button(text="👥 عضو شدن توی گروه",    callback_data="mem:join_group")
    b.button(text="🤖 ربات ممبر گیر",       callback_data="mem:robot_member")
    b.button(text="🔙 برگشت",               callback_data="menu:main")
    b.adjust(1)
    return b.as_markup()


def robot_member_menu() -> InlineKeyboardMarkup:
    """منوی ربات ممبر گیر"""
    b = InlineKeyboardBuilder()
    b.button(text="✅ عضویت",              callback_data="robmem:join")
    b.button(text="💎 speedy — الماس",     callback_data="robmem:speedy")
    b.button(text="🚪 ترک کردن",           callback_data="robmem:leave")
    b.button(text="🔙 برگشت",             callback_data="robmem:back")
    b.adjust(1)
    return b.as_markup()


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
    b.button(text="📋 لیست کامل",    callback_data="acc:list:0")
    b.button(text="➕ افزودن جدید",  callback_data="acc:add")
    b.button(text="🔄 چرخش فوری",   callback_data="acc:rotate")
    b.button(text="🧹 حذف flood‌ها", callback_data="acc:cleanup")
    b.button(text="📥 بکاپ الان",    callback_data="acc:backup")
    b.button(text="🔙 برگشت",        callback_data="menu:main")
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
        _SHIFT_EMOJIS = ["1️⃣","2️⃣","3️⃣","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]
        sh = int(a.get("shift") or 1) - 1
        shift_icon = _SHIFT_EMOJIS[sh] if 0 <= sh < len(_SHIFT_EMOJIS) else "🔢"
        b.button(text=f"{icon} {shift_icon} {a['phone']}",
                 callback_data=f"acc:info:{a['id']}")
    b.adjust(1)

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️ قبلی",        callback_data=f"acc:list:{page-1}"))
    nav.append(    InlineKeyboardButton(text=f"📄 {page+1}/{tot}", callback_data="acc:noop"))
    if e < len(accounts):
        nav.append(InlineKeyboardButton(text="بعدی ➡️",         callback_data=f"acc:list:{page+1}"))

    b.row(*nav)
    b.row(
        InlineKeyboardButton(text="🔄 رفرش",  callback_data=f"acc:list:{page}"),
        InlineKeyboardButton(text="🔙 برگشت", callback_data="menu:accounts"),
    )
    return b.as_markup()


def stats_menu() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="📊 آمار کلی",       callback_data="stats:general")
    b.button(text="📈 آمار ۲۴ ساعت",   callback_data="stats:daily")
    b.button(text="🔄 چرخه شیفت",      callback_data="stats:shift")
    b.button(text="📉 نمودار موفقیت",  callback_data="stats:chart")
    b.button(text="🔙 برگشت",          callback_data="menu:main")
    b.adjust(2)
    return b.as_markup()


def settings_menu() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="⏱️ بازه تایم شیفت",    callback_data="set:shift_timing")
    b.button(text="🔢 انتخاب شیفت فعال",  callback_data="set:shift_active")
    b.button(text="🔢 تعداد شیفت‌ها",      callback_data="set:num_shifts")
    b.button(text="🛡️ وضعیت نگهبان",      callback_data="set:guardian")
    b.button(text="💾 بکاپ",               callback_data="set:backup")
    b.button(text="🔒 تنظیمات ضد لیمیت",  callback_data="set:viewguard")
    b.button(text="🔙 برگشت",              callback_data="menu:main")
    b.adjust(2)
    return b.as_markup()


def viewguard_menu() -> InlineKeyboardMarkup:
    """منوی تنظیمات ViewGuard"""
    b = InlineKeyboardBuilder()
    b.button(text="📊 آمار لحظه‌ای",      callback_data="vg:stats")
    b.button(text="🔄 ریست آمار امروز",   callback_data="vg:reset")
    b.button(text="⚙️ تنظیم سهمیه روزانه", callback_data="vg:set_daily")
    b.button(text="⏳ تنظیم فاصله ویو",   callback_data="vg:set_gap")
    b.button(text="🔙 برگشت",             callback_data="menu:settings")
    b.adjust(2)
    return b.as_markup()


def group_menu() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✏️ تنظیم آیدی گروه",       callback_data="grp:set")
    b.button(text="👥 عضویت همه اکانت‌ها",    callback_data="grp:join")
    b.button(text="📊 چک عضویت‌ها",            callback_data="grp:check")
    b.button(text="🆔 نمایش گروه فعلی",        callback_data="grp:info")
    b.button(text="🩺 تشخیص ویو",              callback_data="grp:diag")
    b.button(text="🧪 تست روی آخرین پیام",     callback_data="grp:test")
    b.button(text="🔁 نوع عملیات (ویو/خواندن)", callback_data="grp:mode")
    b.button(text="🔙 برگشت",                  callback_data="menu:main")
    b.adjust(1)
    return b.as_markup()


def shift_timing_menu() -> InlineKeyboardMarkup:
    """منوی پیش‌فرض‌های بازه شیفت"""
    b = InlineKeyboardBuilder()
    presets = [
        ("⚡ ۵-۱۰ دقیقه",   "5",  "10"),
        ("🔵 ۱۵-۳۰ دقیقه",  "15", "30"),
        ("🟢 ۲۵-۴۵ دقیقه",  "25", "45"),
        ("🟡 ۳۰-۶۰ دقیقه",  "30", "60"),
        ("🔴 ۴۵-۹۰ دقیقه",  "45", "90"),
    ]
    for label, mn, mx in presets:
        b.button(text=label, callback_data=f"stm:preset:{mn}:{mx}")
    b.button(text="✏️ وارد کردن دستی", callback_data="stm:custom")
    b.button(text="🔙 برگشت",          callback_data="menu:main")
    b.adjust(1)
    return b.as_markup()


def num_shifts_menu(current: int) -> InlineKeyboardMarkup:
    """منوی تغییر تعداد شیفت‌ها با دکمه‌های + و -"""
    b = InlineKeyboardBuilder()
    if current > 1:
        b.button(text=f"➖ کم کردن  ({current - 1})", callback_data=f"ns:set:{current - 1}")
    if current < 20:
        b.button(text=f"➕ اضافه کردن  ({current + 1})", callback_data=f"ns:set:{current + 1}")
    b.button(text="🔄 توزیع مجدد اکانت‌ها", callback_data="ns:redistribute")
    b.button(text="🔙 برگشت به تنظیمات", callback_data="menu:settings")
    b.adjust(2, 1, 1)
    return b.as_markup()


def shift_select_menu(current: int, num_shifts: int = 0) -> InlineKeyboardMarkup:
    """منوی انتخاب شیفت فعال (داینامیک) + حالت همه شیفت‌ها (0)"""
    if num_shifts <= 0:
        try:
            from core.pool import POOL
            num_shifts = POOL.num_shifts
        except Exception:
            num_shifts = 4
    b = InlineKeyboardBuilder()
    for i in range(1, num_shifts + 1):
        mark = "✅ " if i == current else ""
        b.button(text=f"{mark}شیفت {i}", callback_data=f"shift:select:{i}")
    all_mark = "✅ " if current == 0 else ""
    b.button(text=f"{all_mark}🌐 همه شیفت‌ها", callback_data="shift:select:0")
    b.button(text="🔙 برگشت", callback_data="menu:main")
    b.adjust(2)
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
