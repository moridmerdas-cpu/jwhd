"""Scheduler — swap شیفت بر اساس زمان‌بندی تنظیم‌شده از ربات"""
import asyncio
import random
import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import Config
from models import database as db

_STATE    = {"swap_count": 0, "last_check": None, "mode": "time"}
_INSTANCE = None


def get_scheduler_instance():
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = AccountScheduler()
    return _INSTANCE


class AccountScheduler:
    CHECK_INTERVAL = 60  # هر ۶۰ ثانیه ساعت رو چک می‌کنه

    def __init__(self):
        self._running    = False
        self._task       = None
        self._next_swap_at = None
        self._current_shift = None

    # ── shift بر اساس ساعت UTC ──────────────────────────
    def _shift_for_now(self) -> int | None:
        hour = datetime.now(timezone.utc).hour
        return db.get_active_shift_for_hour(hour)

    # ── loop اصلی ───────────────────────────────────────
    async def rotation_loop(self):
        from core.pool import POOL
        self._running = True

        # شیفت اولیه
        target = self._shift_for_now()
        if target is not None and target != POOL.active_shift:
            POOL.active_shift    = target
            self._current_shift  = target
        else:
            self._current_shift  = POOL.active_shift

        db.debug_log("scheduler", "start", "OK",
                     f"shift {self._current_shift} | mode=time | check={self.CHECK_INTERVAL}s")

        while self._running:
            try:
                await asyncio.sleep(self.CHECK_INTERVAL)
                target = self._shift_for_now()
                if target is None:
                    continue
                if target != POOL.active_shift:
                    old                  = POOL.active_shift
                    POOL.active_shift    = target
                    self._current_shift  = target
                    _STATE["swap_count"] += 1
                    db.debug_log("scheduler", "swap", "OK",
                                 f"⏰ {old} → {target} | #{_STATE['swap_count']}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                db.debug_log("scheduler", "loop", "ERROR", f"{type(e).__name__}: {e}")
                await asyncio.sleep(5)

    # ── چرخش فوری دستی ──────────────────────────────────
    async def rotate_now(self):
        from core.pool import POOL
        schedules = db.get_shift_schedules()
        enabled   = [s["shift_num"] for s in schedules if s["enabled"]]
        if not enabled:
            return POOL.active_shift
        cur = POOL.active_shift
        idx = enabled.index(cur) if cur in enabled else -1
        nxt = enabled[(idx + 1) % len(enabled)]
        POOL.active_shift   = nxt
        self._current_shift = nxt
        db.debug_log("scheduler", "rotate_now", "OK", f"{cur} → {nxt}")
        return nxt

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
