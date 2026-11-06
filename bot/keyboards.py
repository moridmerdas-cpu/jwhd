"""کیبوردها — نسخه بهبودیافته با دکمه‌های رنگی و منظم"""
from aiogram.types import (ReplyKeyboardMarkup, KeyboardButton,
                          InlineKeyboardMarkup, InlineKeyboardButton)


# ═══════════════════════════════════════════════════════
# منوی اصلی (Reply)
# ═══════════════════════════════════════════════════════
def main_menu():
    kb = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(KeyboardButton("➕ افزودن اکانت"), KeyboardButton("📊 وضعیت زنده"))
    kb.add(KeyboardButton("👥 مدیریت اکانت‌ها"), KeyboardButton("📈 آمار پیشرفته"))
    kb.add(KeyboardButton("🎬 روشن/خاموش ویو"), KeyboardButton("🔄 چرخش دستی"))
    kb.add(KeyboardButton("⚙️ تنظیمات"), KeyboardButton("📢 کانال هدف"))
    kb.add(KeyboardButton("❓ راهنما"))
    return kb


# ═══ منوی ویو ═══
def view_toggle_menu(current_paused: bool):
    """منوی توقف/روشن ویو"""
    kb = InlineKeyboardMarkup(row_width=1)
    if current_paused:
        kb.add(InlineKeyboardButton(
            "▶️ روشن کردن ویو",
            callback_data="view:resume"
        ))
    else:
        kb.add(InlineKeyboardButton(
            "⏸️  توقف ویو",
            callback_data="view:pause"
        ))
    kb.add(InlineKeyboardButton(
        "🔄 بروزرسانی وضعیت",
        callback_data="view:refresh"
    ))
    kb.add(InlineKeyboardButton(
        "🔙 برگشت",
        callback_data="menu:main"
    ))
    return kb


# ═══════════════════════════════════════════════════════
# منوی وضعیت زنده
# ═══════════════════════════════════════════════════════
def status_menu():
    kb = InlineKeyboardMarkup(row_width=3)
    kb.add(
        InlineKeyboardButton("🟢 آنلاین", callback_data="status:online"),
        InlineKeyboardButton("💤 idle", callback_data="status:idle"),
        InlineKeyboardButton("🔴 خطا", callback_data="status:error"),
    )
    kb.add(
        InlineKeyboardButton("🟡 Flood", callback_data="status:flood"),
        InlineKeyboardButton("📊 کل", callback_data="status:all"),
        InlineKeyboardButton("🔙 برگشت", callback_data="menu:main"),
    )
    kb.add(InlineKeyboardButton("🔄 بروزرسانی زنده", callback_data="status:refresh"))
    return kb


# ═══════════════════════════════════════════════════════
# منوی مدیریت اکانت‌ها
# ═══════════════════════════════════════════════════════
def accounts_menu():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("📋 لیست کامل", callback_data="acc:list:0"),
        InlineKeyboardButton("➕ افزودن جدید", callback_data="acc:add"),
    )
    kb.add(
        InlineKeyboardButton("🔄 چرخش فوری", callback_data="acc:rotate"),
        InlineKeyboardButton("🧹 حذف flood‌ها", callback_data="acc:cleanup"),
    )
    kb.add(
        InlineKeyboardButton("📥 بکاپ الان", callback_data="acc:backup"),
        InlineKeyboardButton("🔙 برگشت", callback_data="menu:main"),
    )
    return kb


# ═══════════════════════════════════════════════════════
# صفحه‌بندی لیست اکانت‌ها
# ═══════════════════════════════════════════════════════
def accounts_list_kb(accounts, page=0, per_page=10):
    kb = InlineKeyboardMarkup(row_width=1)
    s = page * per_page
    e = s + per_page
    total_pages = (len(accounts) + per_page - 1) // per_page

    for a in accounts[s:e]:
        icon = {
            "online": "🟢", "flood": "🟡",
            "error": "🔴", "idle": "💤", "dead": "⚫"
        }.get(a.get("status", "idle"), "⚪")
        shift_icon = "🅰️" if a.get("shift") == "A" else "🅱️"
        kb.add(InlineKeyboardButton(
            f"{icon} {shift_icon} {a['phone']}",
            callback_data=f"acc:info:{a['id']}"
        ))

    # نوار ناوبری
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ قبلی", callback_data=f"acc:list:{page-1}"))
    nav.append(InlineKeyboardButton(f"📄 {page+1}/{total_pages}", callback_data="acc:noop"))
    if e < len(accounts):
        nav.append(InlineKeyboardButton("بعدی ➡️", callback_data=f"acc:list:{page+1}"))
    kb.row(*nav)

    kb.add(
        InlineKeyboardButton("🔄 رفرش", callback_data=f"acc:list:{page}"),
        InlineKeyboardButton("🔙 برگشت", callback_data="menu:accounts"),
    )
    return kb


# ═══════════════════════════════════════════════════════
# منوی آمار پیشرفته
# ═══════════════════════════════════════════════════════
def stats_menu():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("📊 آمار کلی", callback_data="stats:general"),
        InlineKeyboardButton("📈 آمار ۲۴ ساعت", callback_data="stats:daily"),
    )
    kb.add(
        InlineKeyboardButton("🌐 وضعیت WARP", callback_data="stats:warp"),
        InlineKeyboardButton("🔄 چرخه شیفت", callback_data="stats:shift"),
    )
    kb.add(
        InlineKeyboardButton("📉 نمودار موفقیت", callback_data="stats:chart"),
        InlineKeyboardButton("🔙 برگشت", callback_data="menu:main"),
    )
    return kb


# ═══════════════════════════════════════════════════════
# منوی تنظیمات
# ═══════════════════════════════════════════════════════
def settings_menu():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("⏱️ طول شیفت", callback_data="set:shift"),
        InlineKeyboardButton("👥 تعداد فعال", callback_data="set:active"),
    )
    kb.add(
        InlineKeyboardButton("🛡️ وضعیت نگهبان", callback_data="set:guardian"),
        InlineKeyboardButton("💾 بکاپ", callback_data="set:backup"),
    )
    kb.add(
        InlineKeyboardButton("📊 WARP", callback_data="set:warp"),
        InlineKeyboardButton("🔙 برگشت", callback_data="menu:main"),
    )
    return kb


# ═══════════════════════════════════════════════════════
# منوی کانال
# ═══════════════════════════════════════════════════════
def channel_menu():
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton("👥 عضویت همه اکانت‌ها", callback_data="ch:join"),
        InlineKeyboardButton("📊 چک عضویت‌ها", callback_data="ch:check"),
        InlineKeyboardButton("📢 نمایش کانال فعلی", callback_data="ch:info"),
        InlineKeyboardButton("🔙 برگشت", callback_data="menu:main"),
    )
    return kb


# ═══════════════════════════════════════════════════════
# تایید
# ═══════════════════════════════════════════════════════
def confirm_menu(action):
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("✅ بله", callback_data=f"cfm:yes:{action}"),
        InlineKeyboardButton("❌ خیر", callback_data=f"cfm:no:{action}"),
    )
    return kb


# ═══════════════════════════════════════════════════════
# انصراف افزودن اکانت
# ═══════════════════════════════════════════════════════
def cancel_menu():
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("❌ انصراف", callback_data="add:cancel"))
    return kb
