"""Scheduler — swap شیفت‌ها با بازه تصادفی قابل تنظیم از ربات"""
import asyncio, random, sys
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import Config
from models import database as db

_STATE = {
    "current_shift":        1,
    "next_swap_at":         None,
    "swap_count":           0,      # تعداد چرخش‌های خودکار موفق
    "manual_swap_count":    0,      # تعداد چرخش‌های دستی موفق
    "total_swap_count":     0,      # جمع کل (خودکار + دستی)
    "last_interval":        0,
    "last_swap_at":         None,   # زمان آخرین چرخش
    "last_activate_result": None,   # نتیجه آخرین activate_shift
    # وقتی rotate_now صدا زده میشه این flag رو true میکنه
    # تا rotation_loop بدونه که شیفت قبلاً چرخیده و دوباره نچرخونه
    "_manual_rotated":      False,
}

_INSTANCE = None


def get_scheduler_instance():
    """تنها نمونه‌ی واقعی scheduler رو برمیگردونه.
    همه‌جا از این استفاده کن — نه AccountScheduler() مستقیم."""
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = AccountScheduler()
    return _INSTANCE


def _get_shift_range():
    """بازه تایم شیفت رو از DB می‌خونه (ثانیه)"""
    try:
        mn = int(db.get_setting("shift_min_sec", Config.SHIFT_MIN_SEC))
        mx = int(db.get_setting("shift_max_sec", Config.SHIFT_MAX_SEC))
        if mn < 30:    mn = 30
        if mx < mn+30: mx = mn + 30
        return mn, mx
    except Exception:
        return Config.SHIFT_MIN_SEC, Config.SHIFT_MAX_SEC


class AccountScheduler:
    def __init__(self):
        self._running = False
        self._task    = None

    # ── read-only views into global state ──────────────────────────────────

    @property
    def _current_shift(self):
        from core.pool import POOL
        return POOL.active_shift

    @property
    def _next_swap_at(self):
        return _STATE["next_swap_at"]

    # ── scheduling helpers ─────────────────────────────────────────────────

    def _schedule_next(self):
        mn, mx = _get_shift_range()
        seconds = random.randint(mn, mx)
        _STATE["last_interval"] = seconds
        _STATE["next_swap_at"]  = datetime.utcnow() + timedelta(seconds=seconds)
        return seconds

    @staticmethod
    def _record_activate(result: dict):
        """نتیجه activate_shift رو در _STATE ذخیره می‌کنه"""
        _STATE["last_activate_result"] = {
            "total":     result.get("total", 0),
            "connected": result.get("connected", 0),
            "at":        datetime.utcnow().strftime("%H:%M:%S"),
        }

    # ── main loop ──────────────────────────────────────────────────────────

    async def rotation_loop(self):
        from core.pool import POOL
        self._running = True
        interval = self._schedule_next()
        db.debug_log("scheduler", "start", "OK",
                     f"shift {POOL.active_shift} next_swap +{interval}s")

        while self._running:
            try:
                now       = datetime.utcnow()
                remaining = (_STATE["next_swap_at"] - now).total_seconds()

                if remaining > 0:
                    await asyncio.sleep(min(remaining, 3))
                    continue

                # ── اگه rotate_now قبلاً manual چرخوند، فقط زمان‌بندی reset کن ──
                if _STATE["_manual_rotated"]:
                    _STATE["_manual_rotated"] = False
                    interval = self._schedule_next()
                    db.debug_log("scheduler", "skip_auto", "OK",
                                 f"manual rotation detected, rescheduled +{interval}s")
                    continue

                # ── چرخش خودکار ──────────────────────────────────────────
                old = POOL.active_shift

                # اگه num_shifts == 1 یا active_shift == 0، چرخشی نیست
                if POOL.num_shifts <= 1 or old == 0:
                    interval = self._schedule_next()
                    db.debug_log("scheduler", "no_cycle", "SKIP",
                                 f"num_shifts={POOL.num_shifts} active={old}, rescheduled +{interval}s")
                    continue

                new = POOL.swap_cycle()
                _STATE["swap_count"]       += 1
                _STATE["total_swap_count"] += 1
                _STATE["last_swap_at"]      = datetime.utcnow().strftime("%H:%M:%S")
                interval = self._schedule_next()

                db.debug_log("scheduler", "swap", "OK",
                             f"🔄 {old}→{new} | +{interval}s | auto#{_STATE['swap_count']} total#{_STATE['total_swap_count']}")

                try:
                    result = await POOL.activate_shift(new)
                    self._record_activate(result)
                    db.debug_log("scheduler", "activate", "OK",
                                 f"shift {new} | {result['connected']}/{result['total']} connected")
                except Exception as ae:
                    db.debug_log("scheduler", "activate", "ERROR",
                                 f"shift {new}: {type(ae).__name__}: {ae}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                db.debug_log("scheduler", "loop", "ERROR", f"{type(e).__name__}: {e}")
                await asyncio.sleep(5)

        self._running = False

    # ── manual rotation (from bot handlers) ───────────────────────────────

    async def rotate_now(self):
        """چرخش دستی فوری — به loop اطلاع میده که دوباره نچرخونه."""
        from core.pool import POOL
        old = POOL.active_shift

        if POOL.num_shifts <= 1 or old == 0:
            return old  # چیزی برای چرخوندن نیست

        new = POOL.swap_cycle()
        _STATE["manual_swap_count"] += 1
        _STATE["total_swap_count"]  += 1
        _STATE["last_swap_at"]       = datetime.utcnow().strftime("%H:%M:%S")
        # به loop بگو که قبلاً چرخیده — فقط زمان‌بندی reset میشه
        _STATE["_manual_rotated"] = True
        # زمان بعدی رو هم از همین لحظه دوباره بچین
        self._schedule_next()

        db.debug_log("scheduler", "rotate_now", "OK",
                     f"🔄 manual {old}→{new} | manual#{_STATE['manual_swap_count']} total#{_STATE['total_swap_count']}")

        try:
            result = await POOL.activate_shift(new)
            self._record_activate(result)
            db.debug_log("scheduler", "rotate_now_activate", "OK",
                         f"shift {new} | {result['connected']}/{result['total']} connected")
        except Exception as ae:
            db.debug_log("scheduler", "rotate_now_activate", "ERROR",
                         f"shift {new}: {type(ae).__name__}: {ae}")

        return new

    # ── lifecycle ──────────────────────────────────────────────────────────

    def start(self):
        """باید روی event loop اجرا بشه (بعد از asyncio.run شروع میشه)"""
        if self._running:
            return  # جلوگیری از دوبار start
        try:
            loop = asyncio.get_running_loop()
            self._task = loop.create_task(self.rotation_loop())
        except RuntimeError:
            db.debug_log("scheduler", "start", "ERROR", "no running event loop")

    def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
