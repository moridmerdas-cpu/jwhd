"""
تست جامع ۳۶۰ درجه — شبیه‌سازی کامل کاربر
هر دکمه، هر منو، هر قابلیت رو تست می‌کنه
"""
import asyncio
import sys
import inspect
from pathlib import Path
from datetime import datetime

sys.path.insert(0, '/root/tg_master_bot')

print()
print("█" * 75)
print(f"  🎭 شبیه‌سازی کامل کاربر — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("█" * 75)

# ═══════════════════════════════════════════════════════════
# Mock Objects
# ═══════════════════════════════════════════════════════════

class FakeChat:
    def __init__(self, uid): self.id = uid

class FakeUser:
    def __init__(self, uid=7598953131, username="admin"):
        self.id = uid
        self.username = username
        self.first_name = "Admin"

class FakeMessage:
    def __init__(self, text="", uid=7598953131):
        self.text = text
        self.from_user = FakeUser(uid)
        self.chat = FakeChat(uid)
        self.responses = []
        self.message_id = 1

    async def answer(self, text, **kwargs):
        self.responses.append({"type": "answer", "text": text, "kwargs": kwargs})
        return self

    async def reply(self, text, **kwargs):
        self.responses.append({"type": "reply", "text": text, "kwargs": kwargs})
        return self

    async def edit_text(self, text, **kwargs):
        self.responses.append({"type": "edit", "text": text, "kwargs": kwargs})
        return self

class FakeCallbackMessage:
    def __init__(self):
        self.text = "previous"
        self.message_id = 1
        self.responses = []

    async def edit_text(self, text, **kwargs):
        self.responses.append({"type": "edit", "text": text, "kwargs": kwargs})
        return self

    async def answer(self, text, **kwargs):
        self.responses.append({"type": "answer", "text": text, "kwargs": kwargs})
        return self

class FakeCallback:
    def __init__(self, data="", uid=7598953131):
        self.data = data
        self.from_user = FakeUser(uid)
        self.message = FakeCallbackMessage()
        self.responses = []

    async def answer(self, text="", **kwargs):
        self.responses.append({"type": "callback_answer", "text": text, "kwargs": kwargs})
        return self


class FakeState:
    def __init__(self):
        self.current_state = None
        self.data = {}

    async def set_state(self, state):
        self.current_state = state
        return self

    async def update_data(self, **kwargs):
        self.data.update(kwargs)

    async def get_data(self):
        return dict(self.data)

    async def finish(self):
        self.current_state = None
        self.data = {}

    async def reset_state(self):
        self.current_state = None


# ═══════════════════════════════════════════════════════════
# Test Framework
# ═══════════════════════════════════════════════════════════

results = {"passed": 0, "failed": 0, "skipped": 0, "details": []}


def header(title):
    print(f"\n{'═' * 75}")
    print(f"  {title}")
    print(f"{'═' * 75}")


def ok(name, detail=""):
    results["passed"] += 1
    print(f"  ✅ {name}" + (f" | {detail}" if detail else ""))


def fail(name, err=""):
    results["failed"] += 1
    print(f"  ❌ {name}" + (f" | {err}" if err else ""))
    results["details"].append({"name": name, "error": str(err)})


def skip(name, reason=""):
    results["skipped"] += 1
    print(f"  ⏭️  {name}" + (f" | {reason}" if reason else ""))


async def test_call(name, coro, expect_response=True):
    """تست یک تابع async"""
    try:
        if asyncio.iscoroutine(coro):
            await coro
        ok(name)
        return True
    except Exception as e:
        fail(name, f"{type(e).__name__}: {e}")
        return False


# ═══════════════════════════════════════════════════════════
# Start
# ═══════════════════════════════════════════════════════════

async def main():
    # import
    try:
        from bot import handlers
        from bot.keyboards import (
            main_menu, status_menu, accounts_menu, accounts_list_kb,
            stats_menu, settings_menu, channel_menu, confirm_menu,
            cancel_menu, view_toggle_menu
        )
        from bot.states import AddAccount
        from models import database as db
        from config import Config
        ok("import ماژول‌ها", "handlers + keyboards + states")
    except Exception as e:
        fail("import ماژول‌ها", e)
        return

    db.init_db()

    # ═══════════════════════════════════════════════════════════
    header("📱 ۱. تست Reply Menu (منوی اصلی)")
    # ═══════════════════════════════════════════════════════════

    buttons = {
        "➕ افزودن اکانت": handlers._add_account_start,
        "📊 وضعیت زنده": handlers.show_status,
        "👥 مدیریت اکانت‌ها": handlers.show_accounts,
        "📈 آمار پیشرفته": handlers.show_stats,
        "🎬 روشن/خاموش ویو": handlers.show_view_toggle,
        "🔄 چرخش دستی": handlers.manual_rotate,
        "⚙️ تنظیمات": handlers.show_settings,
        "📢 کانال هدف": handlers.show_channel,
        "❓ راهنما": handlers.cmd_help,
    }

    for btn_text, fn in buttons.items():
        msg = FakeMessage(text=btn_text)
        state = FakeState()
        try:
            sig = inspect.signature(fn)
            params = list(sig.parameters.keys())
            if "state" in params:
                await fn(msg, state)
            else:
                await fn(msg)
            if msg.responses:
                ok(f"دکمه {btn_text}", f"پاسخ: {msg.responses[0]['text'][:40]}")
            else:
                fail(f"دکمه {btn_text}", "بدون پاسخ")
        except Exception as e:
            fail(f"دکمه {btn_text}", f"{type(e).__name__}: {e}")

    # ═══════════════════════════════════════════════════════════
    header("📋 ۲. تست Commands")
    # ═══════════════════════════════════════════════════════════

    for cmd_name, fn in [
        ("/start", handlers.cmd_start),
        ("/help", handlers.cmd_help),
    ]:
        msg = FakeMessage(text=cmd_name)
        try:
            await fn(msg)
            ok(cmd_name, f"{len(msg.responses)} پاسخ")
        except Exception as e:
            fail(cmd_name, f"{type(e).__name__}: {e}")

    # ═══════════════════════════════════════════════════════════
    header("🔘 ۳. تست Inline Callbacks — وضعیت")
    # ═══════════════════════════════════════════════════════════

    for cb_data in ["status:online", "status:idle", "status:error", "status:flood", "status:all", "status:refresh"]:
        cb = FakeCallback(data=cb_data)
        try:
            await handlers.cb_status(cb)
            ok(f"callback {cb_data}", f"{len(cb.responses)} پاسخ")
        except Exception as e:
            fail(f"callback {cb_data}", f"{type(e).__name__}: {e}")

    # ═══════════════════════════════════════════════════════════
    header("🔘 ۴. تست Inline Callbacks — آمار")
    # ═══════════════════════════════════════════════════════════

    for cb_data in ["stats:general", "stats:daily", "stats:warp", "stats:shift", "stats:chart"]:
        cb = FakeCallback(data=cb_data)
        try:
            await handlers.cb_stats(cb)
            ok(f"callback {cb_data}", f"{len(cb.responses)} پاسخ")
        except Exception as e:
            fail(f"callback {cb_data}", f"{type(e).__name__}: {e}")

    # ═══════════════════════════════════════════════════════════
    header("🔘 ۵. تست Inline Callbacks — کانال")
    # ═══════════════════════════════════════════════════════════

    for cb_data in ["ch:info"]:
        cb = FakeCallback(data=cb_data)
        try:
            await handlers.cb_channel(cb)
            ok(f"callback {cb_data}", f"{len(cb.responses)} پاسخ")
        except Exception as e:
            fail(f"callback {cb_data}", f"{type(e).__name__}: {e}")

    # ═══════════════════════════════════════════════════════════
    header("🔘 ۶. تست Inline Callbacks — تنظیمات")
    # ═══════════════════════════════════════════════════════════

    for cb_data in ["set:shift", "set:active", "set:guardian", "set:backup", "set:warp"]:
        cb = FakeCallback(data=cb_data)
        try:
            await handlers.cb_settings(cb)
            ok(f"callback {cb_data}", f"{len(cb.responses)} پاسخ")
        except Exception as e:
            fail(f"callback {cb_data}", f"{type(e).__name__}: {e}")

    # ═══════════════════════════════════════════════════════════
    header("🔘 ۷. تست Inline Callbacks — اکانت‌ها")
    # ═══════════════════════════════════════════════════════════

    state = FakeState()
    for cb_data in ["acc:list:0", "acc:add", "acc:rotate", "acc:cleanup", "acc:backup", "acc:noop"]:
        cb = FakeCallback(data=cb_data)
        try:
            await handlers.cb_accounts(cb, state)
            ok(f"callback {cb_data}", f"{len(cb.responses)} پاسخ")
        except Exception as e:
            fail(f"callback {cb_data}", f"{type(e).__name__}: {e}")

    # ═══════════════════════════════════════════════════════════
    header("🎬 ۸. تست دکمه توقف/روشن ویو")
    # ═══════════════════════════════════════════════════════════

    from core.listener import set_view_paused, is_view_paused

    # اولیه
    initial = is_view_paused()
    ok(f"وضعیت اولیه", f"paused = {initial}")

    # توقف
    state = FakeState()
    cb = FakeCallback(data="view:pause")
    try:
        await handlers.cb_view_toggle(cb, state)
        paused = is_view_paused()
        if paused:
            ok("view:pause", "✅ متوقف شد")
        else:
            fail("view:pause", "وضعیت تغییر نکرد")
    except Exception as e:
        fail("view:pause", f"{type(e).__name__}: {e}")

    # روشن
    cb = FakeCallback(data="view:resume")
    try:
        await handlers.cb_view_toggle(cb, state)
        paused = is_view_paused()
        if not paused:
            ok("view:resume", "✅ روشن شد")
        else:
            fail("view:resume", "وضعیت تغییر نکرد")
    except Exception as e:
        fail("view:resume", f"{type(e).__name__}: {e}")

    # ═══════════════════════════════════════════════════════════
    header("➕ ۹. تست FSM افزودن اکانت — مرحله به مرحله")
    # ═══════════════════════════════════════════════════════════

    state = FakeState()

    # مرحله ۱: شروع
    msg = FakeMessage(text="➕ افزودن اکانت")
    try:
        await handlers._add_account_start(msg, state)
        if msg.responses:
            ok("FSM مرحله ۱: شروع", f"پاسخ: {msg.responses[0]['text'][:50]}")
        else:
            fail("FSM مرحله ۱: شروع", "بدون پاسخ")
    except Exception as e:
        fail("FSM مرحله ۱: شروع", f"{type(e).__name__}: {e}")

    # مرحله ۲: شماره نامعتبر
    msg = FakeMessage(text="1234")
    try:
        await handlers.add_phone(msg, state)
        if msg.responses and ("فرمت" in msg.responses[0]['text'] or "❌" in msg.responses[0]['text']):
            ok("FSM مرحله ۲: شماره نامعتبر", "رد شد درست")
        else:
            fail("FSM مرحله ۲: شماره نامعتبر", "رد نشد")
    except Exception as e:
        fail("FSM مرحله ۲: شماره نامعتبر", f"{type(e).__name__}: {e}")

    # مرحله ۳: شماره تکراری (اگه وجود داره)
    accounts = db.get_all_accounts()
    if accounts:
        existing_phone = accounts[0]["phone"]
        msg = FakeMessage(text=existing_phone)
        try:
            await handlers.add_phone(msg, state)
            if msg.responses and "قبلاً" in msg.responses[0]['text']:
                ok("FSM مرحله ۳: شماره تکراری", "رد شد درست")
            else:
                fail("FSM مرحله ۳: شماره تکراری", "رد نشد")
        except Exception as e:
            fail("FSM مرحله ۳: شماره تکراری", f"{type(e).__name__}: {e}")

    # ═══════════════════════════════════════════════════════════
    header("🛑 ۱۰. تست Cancel افزودن اکانت")
    # ═══════════════════════════════════════════════════════════

    state = FakeState()
    cb = FakeCallback(data="add:cancel")
    try:
        await handlers.add_cancel(cb, state)
        ok("add:cancel", f"{len(cb.responses)} پاسخ")
    except Exception as e:
        fail("add:cancel", f"{type(e).__name__}: {e}")

    # ═══════════════════════════════════════════════════════════
    header("🛡️ ۱۱. تست غیر ادمین (access control)")
    # ═══════════════════════════════════════════════════════════

    non_admin_id = 999999999
    msg = FakeMessage(text="/start", uid=non_admin_id)
    try:
        await handlers.cmd_start(msg)
        if msg.responses and ("دسترسی" in msg.responses[0]['text']):
            ok("غیر ادمین /start", "رد شد درست")
        else:
            fail("غیر ادمین /start", "رد نشد")
    except Exception as e:
        fail("غیر ادمین /start", f"{type(e).__name__}: {e}")

    # ═══════════════════════════════════════════════════════════
    header("📊 ۱۲. تست دیتابیس و سشن‌ها")
    # ═══════════════════════════════════════════════════════════

    try:
        accounts = db.get_all_accounts()
        ok(f"خواندن {len(accounts)} اکانت")

        if accounts:
            # تست get_session
            ss = db.get_session(accounts[0]["phone"])
            if ss and len(ss) > 100:
                ok("decrypt سشن", f"طول: {len(ss)} کاراکتر")
            else:
                fail("decrypt سشن", f"طول نامعتبر: {len(ss) if ss else 'None'}")
    except Exception as e:
        fail("دیتابیس", f"{type(e).__name__}: {e}")

    # ═══════════════════════════════════════════════════════════
    header("🔧 ۱۳. تست Engine و WARP")
    # ═══════════════════════════════════════════════════════════

    try:
        from core.engine import make_client, instant_view, health_check
        ok("import engine")
    except Exception as e:
        fail("import engine", f"{type(e).__name__}: {e}")

    try:
        from core.warp_pool import get_all_configs, get_port_from_conf
        configs = get_all_configs()
        ok(f"warp_pool", f"{len(configs)} کانفیگ")
    except Exception as e:
        fail("warp_pool", f"{type(e).__name__}: {e}")

    # ═══════════════════════════════════════════════════════════
    header("🩺 ۱۴. تست Pool و Watchdog")
    # ═══════════════════════════════════════════════════════════

    try:
        from core.pool import POOL
        ok("import pool", f"clients: {len(POOL.clients)}, phones: {len(POOL.phones)}")
    except Exception as e:
        fail("import pool", f"{type(e).__name__}: {e}")

    try:
        from core.proxy_watchdog import ProxyWatchdog, ACCOUNT_PROXY, _load_account_proxy
        _load_account_proxy()
        ok("import watchdog", f"{len(ACCOUNT_PROXY)} تخصیص")
    except Exception as e:
        fail("import watchdog", f"{type(e).__name__}: {e}")

    try:
        from core.self_heal import SelfHealGuardian
        ok("import self_heal")
    except Exception as e:
        fail("import self_heal", f"{type(e).__name__}: {e}")

    try:
        from core.session_lock import get_lock, SessionGuard
        ok("import session_lock")
    except Exception as e:
        fail("import session_lock", f"{type(e).__name__}: {e}")

    # ═══════════════════════════════════════════════════════════
    header("💾 ۱۵. تست بکاپ")
    # ═══════════════════════════════════════════════════════════

    try:
        from core.backup import create_backup, BACKUP_DIR
        backup_file = create_backup()
        if backup_file and backup_file.exists():
            size_kb = backup_file.stat().st_size // 1024
            ok(f"بکاپ", f"{backup_file.name} ({size_kb}KB)")
        else:
            fail("بکاپ", "فایل ساخته نشد")
    except Exception as e:
        fail("بکاپ", f"{type(e).__name__}: {e}")

    # ═══════════════════════════════════════════════════════════
    header("⏰ ۱۶. تست Scheduler")
    # ═══════════════════════════════════════════════════════════

    try:
        from core.scheduler import AccountScheduler
        sched = AccountScheduler()
        active = await sched.get_active_shift()
        ok(f"شیفت فعال", f"{active}")
    except Exception as e:
        fail("scheduler", f"{type(e).__name__}: {e}")

    # ═══════════════════════════════════════════════════════════
    header("🎨 ۱۷. تست Keyboards")
    # ═══════════════════════════════════════════════════════════

    for kb_name, kb in [
        ("main_menu", main_menu),
        ("status_menu", status_menu),
        ("accounts_menu", accounts_menu),
        ("stats_menu", stats_menu),
        ("settings_menu", settings_menu),
        ("channel_menu", channel_menu),
        ("cancel_menu", cancel_menu),
    ]:
        try:
            result = kb()
            ok(f"keyboard {kb_name}")
        except Exception as e:
            fail(f"keyboard {kb_name}", f"{type(e).__name__}: {e}")

    # ═══════════════════════════════════════════════════════════
    # گزارش نهایی
    # ═══════════════════════════════════════════════════════════

    print()
    print("█" * 75)
    print("  🏁 گزارش نهایی")
    print("█" * 75)
    print()
    print(f"  ✅ موفق: {results['passed']}")
    print(f"  ❌ ناموفق: {results['failed']}")
    print(f"  ⏭️  رد شده: {results['skipped']}")
    total = results['passed'] + results['failed']
    if total > 0:
        pct = results['passed'] * 100 // total
        print(f"  📊 نرخ موفقیت: {pct}%")

    if results["details"]:
        print()
        print("  ⚠️  خطاها:")
        for d in results["details"]:
            print(f"     ❌ {d['name']}")
            print(f"        {d['error'][:100]}")

    print()
    print("█" * 75)


if __name__ == "__main__":
    asyncio.run(main())
