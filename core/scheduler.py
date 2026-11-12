"""Scheduler — swap شیفت‌ها با بازه تصادفی قابل تنظیم از ربات"""
import asyncio, random, sys
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import Config
from models import database as db

_STATE = {"current_shift": 1, "next_swap_at": None, "swap_count": 0, "last_interval": 0}
_INSTANCE = None


def get_scheduler_instance():
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = AccountScheduler()
    return _INSTANCE


def _get_shift_range():
    """بازه تایم شیفت رو از DB می‌خونه (ثانیه)"""
    try:
        mn = int(db.get_setting("shift_min_sec", Config.SHIFT_MIN_SEC))
        mx = int(db.get_setting("shift_max_sec", Config.SHIFT_MAX_SEC))
        if mn < 30:   mn = 30
        if mx < mn+30: mx = mn + 30
        return mn, mx
    except Exception:
        return Config.SHIFT_MIN_SEC, Config.SHIFT_MAX_SEC


class AccountScheduler:
    def __init__(self):
        self._running = False
        self._task = None

    @property
    def _current_shift(self):
        from core.pool import POOL
        return POOL.active_shift

    @property
    def _next_swap_at(self):
        return _STATE["next_swap_at"]

    def _schedule_next(self):
        mn, mx = _get_shift_range()
        seconds = random.randint(mn, mx)
        _STATE["last_interval"] = seconds
        _STATE["next_swap_at"] = datetime.utcnow() + timedelta(seconds=seconds)
        return seconds

    async def rotation_loop(self):
        from core.pool import POOL
        self._running = True
        interval = self._schedule_next()
        db.debug_log("scheduler", "start", "OK",
                     f"shift {POOL.active_shift} swap +{interval}s")
        while self._running:
            try:
                now = datetime.utcnow()
                remaining = (_STATE["next_swap_at"] - now).total_seconds()
                if remaining > 0:
                    await asyncio.sleep(min(remaining, 3))
                    continue
                old = POOL.active_shift
                new = (old % POOL.num_shifts) + 1
                _STATE["swap_count"] += 1
                interval = self._schedule_next()
                result = await POOL.activate_shift(new)
                db.debug_log("scheduler", "swap", "OK",
                             f"🔄 {old} → {new} | +{interval}s | #{_STATE['swap_count']} | connected:{result['connected']}/{result['total']}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                db.debug_log("scheduler", "loop", "ERROR", f"{type(e).__name__}: {e}")
                await asyncio.sleep(5)

    async def rotate_now(self):
        from core.pool import POOL
        old = POOL.active_shift
        new = (old % POOL.num_shifts) + 1
        self._schedule_next()
        await POOL.activate_shift(new)
        return new

    def start(self):
        try:
            loop = asyncio.get_running_loop()
            self._task = loop.create_task(self.rotation_loop())
        except RuntimeError:
            pass

    def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
