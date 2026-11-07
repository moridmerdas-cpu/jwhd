"""Scheduler — swap بین 4 شیفت هر 50-70s"""
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


class AccountScheduler:
    def __init__(self):
        self._running = False
        self._task = None

    async def get_active_shift(self):
        from core.pool import POOL
        return POOL.active_shift

    def _schedule_next(self):
        seconds = random.randint(50, 70)
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
                new = POOL.swap_cycle()
                _STATE["swap_count"] += 1
                interval = self._schedule_next()
                db.debug_log("scheduler", "swap", "OK",
                             f"🔄 {old} → {new} | +{interval}s | #{_STATE['swap_count']}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                db.debug_log("scheduler", "loop", "ERROR", f"{type(e).__name__}: {e}")
                await asyncio.sleep(5)

    async def rotate_now(self):
        from core.pool import POOL
        old = POOL.active_shift
        new = POOL.swap_cycle()
        self._schedule_next()
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
