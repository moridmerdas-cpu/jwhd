"""
Anti-Lock — ضد قفل هوشمند
- views هر پست رو track می‌کنه
- اگه ۳ پست آخر views<3 → listener pause
- صبر هوشمند + resume
"""
import asyncio
import time as _time
import sys
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import Config
from models import database as db


class AntiLock:
    def __init__(self):
        self.recent_views = []  # [(ts, msg_id, views), ...]
        self.paused = False
        self.pause_until = 0
        self.pause_duration = 300  # 5 دقیقه شروع
        self.max_pause = 1800      # حداکثر 30 دقیقه
        self.pause_count = 0
        self.last_check = 0

    def record(self, msg_id, views):
        """ثبت views پست"""
        self.recent_views.append((_time.time(), msg_id, views))
        # فقط ۱۰ تای آخر
        if len(self.recent_views) > 10:
            self.recent_views = self.recent_views[-10:]

    def should_pause(self):
        """آیا باید pause بشه؟"""
        if len(self.recent_views) < 3:
            return False
        # ۳ پست آخر
        last3 = self.recent_views[-3:]
        # اگه همه < 3
        if all(v < 3 for _, _, v in last3):
            return True
        return False

    def should_resume(self):
        """آیا باید resume بشه؟"""
        if not self.paused:
            return False
        return _time.time() >= self.pause_until

    def pause(self):
        """Pause listener"""
        self.paused = True
        self.pause_count += 1
        # هر بار دو برابر
        self.pause_duration = min(self.pause_duration * 2, self.max_pause)
        self.pause_until = _time.time() + self.pause_duration
        db.debug_log("anti_lock", "pause", "WARN",
                     f"rate-limit detected! pause {self.pause_duration}s (#{self.pause_count})")

    def resume(self):
        """Resume listener"""
        self.paused = False
        # نصف کردن pause duration بعد از resume موفق
        self.pause_duration = max(self.pause_duration // 2, 300)
        # پاک کردن history
        self.recent_views = []
        db.debug_log("anti_lock", "resume", "OK",
                     f"resumed | next pause: {self.pause_duration}s")

    def remaining_pause(self):
        """چند ثانیه مونده"""
        return max(0, int(self.pause_until - _time.time()))

    def status(self):
        """وضعیت"""
        return {
            "paused": self.paused,
            "remaining": self.remaining_pause(),
            "recent_views": [v for _, _, v in self.recent_views[-5:]],
            "pause_count": self.pause_count,
        }


ANTI_LOCK = AntiLock()
