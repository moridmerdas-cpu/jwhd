"""
ViewGuard — جلوگیری از view_limit با شبیه‌سازی رفتار طبیعی کاربر

مشکل اصلی:
  تلگرام وقتی می‌بینه یه اکانت با pattern ثابت و سریع GetMessagesViewsRequest
  میزنه، view_limit میده. راه‌حل: هر اکانت باید مثل یه کاربر واقعی رفتار کنه.

استراتژی‌ها:
  1. هر اکانت روزانه سهمیه ویو داره (نه بیشتر از MAX_VIEWS_PER_DAY)
  2. هر اکانت روی هر پست فقط یه بار ویو میزنه (تکرار نمیشه)
  3. تاخیر بین ویوهای هر اکانت: حداقل MIN_GAP_SEC ثانیه
  4. اکانت‌های مختلف با آفست زمانی متفاوت ویو میزنن (نه همه با هم)
  5. اگه اکانت flood خورد، cooldown خودکار میشه
"""

import time as _time
import random
import asyncio
from collections import defaultdict

# ───────── تنظیمات ─────────
MAX_VIEWS_PER_DAY   = 80     # حداکثر ویو روزانه هر اکانت
MIN_GAP_SEC         = 8.0    # حداقل فاصله بین دو ویو متوالی از یه اکانت (ثانیه)
MAX_GAP_SEC         = 25.0   # حداکثر فاصله طبیعی
FLOOD_COOLDOWN_MIN  = 300    # cooldown بعد از flood (ثانیه) — حداقل
FLOOD_COOLDOWN_MAX  = 900    # cooldown بعد از flood (ثانیه) — حداکثر
SEEN_MSG_TTL        = 86400  # چقدر "دیده‌شده" نگه داریم (۲۴ ساعت)


class _AccountState:
    """وضعیت هر اکانت برای view_guard"""
    __slots__ = ("last_view_at", "views_today", "day_key",
                 "flood_until", "seen_msgs", "seen_times")

    def __init__(self):
        self.last_view_at: float = 0.0
        self.views_today:  int   = 0
        self.day_key:      str   = ""
        self.flood_until:  float = 0.0
        self.seen_msgs:    set   = set()   # msg_id هایی که قبلاً ویو زده
        self.seen_times:   dict  = {}      # msg_id -> timestamp (برای TTL)


class ViewGuard:
    """
    نگهبان ویو — هر اکانت باید از اینجا اجازه بگیره.

    استفاده:
        guard = ViewGuard()

        # قبل از ویو:
        ok, wait = guard.can_view(phone, msg_id)
        if not ok:
            # skip یا صبر کن
            pass

        # بعد از ویو موفق:
        guard.on_view_ok(phone, msg_id)

        # بعد از flood:
        guard.on_flood(phone, seconds)
    """

    def __init__(self):
        self._state: dict[str, _AccountState] = defaultdict(_AccountState)
        self._lock = asyncio.Lock()

    def _today(self) -> str:
        from datetime import date
        return date.today().isoformat()

    def _st(self, phone: str) -> _AccountState:
        return self._state[phone]

    def _reset_day_if_needed(self, st: _AccountState):
        today = self._today()
        if st.day_key != today:
            st.day_key      = today
            st.views_today  = 0
            # پاک کردن seen_msgs قدیمی
            now = _time.time()
            old = [mid for mid, ts in st.seen_times.items() if now - ts > SEEN_MSG_TTL]
            for mid in old:
                st.seen_msgs.discard(mid)
                del st.seen_times[mid]

    def can_view(self, phone: str, msg_id: int) -> tuple[bool, float]:
        """
        بررسی اینکه آیا این اکانت می‌تونه الان ویو بزنه.
        برمیگردونه: (مجاز_هست, چقدر_صبر_کنه)
        اگه مجاز نیست، wait > 0 یعنی بعداً ممکنه؛ wait == -1 یعنی skip کن.
        """
        st = self._st(phone)
        self._reset_day_if_needed(st)
        now = _time.time()

        # ۱. flood فعاله؟
        if st.flood_until > now:
            return False, st.flood_until - now

        # ۲. سهمیه روزانه تموم شده؟
        if st.views_today >= MAX_VIEWS_PER_DAY:
            return False, -1   # امروز skip — فردا reset میشه

        # ۳. این پست رو قبلاً ویو زده؟
        if msg_id in st.seen_msgs:
            return False, -1   # skip کامل

        # ۴. فاصله کافی از ویو قبلی داشته؟
        gap = now - st.last_view_at
        if gap < MIN_GAP_SEC:
            return False, MIN_GAP_SEC - gap

        return True, 0.0

    def on_view_ok(self, phone: str, msg_id: int):
        """ویو موفق بود — ثبت کن"""
        st = self._st(phone)
        self._reset_day_if_needed(st)
        now = _time.time()
        st.last_view_at = now
        st.views_today  += 1
        st.seen_msgs.add(msg_id)
        st.seen_times[msg_id] = now

    def on_flood(self, phone: str, seconds: int):
        """flood خورد — cooldown تنظیم کن"""
        st = self._st(phone)
        cooldown = max(seconds, random.randint(FLOOD_COOLDOWN_MIN, FLOOD_COOLDOWN_MAX))
        st.flood_until = _time.time() + cooldown

    def eligible_phones(self, phones: list[str], msg_id: int) -> list[str]:
        """
        از لیست phones، فقط اونایی رو برمیگردونه که
        واقعاً مجاز به ویو هستن (flood نیستن، سهمیه دارن، تکراری نیستن).
        """
        result = []
        for p in phones:
            ok, wait = self.can_view(p, msg_id)
            if ok:
                result.append(p)
        return result

    def stats(self) -> dict:
        """آمار کلی برای debug"""
        now = _time.time()
        flooded   = sum(1 for st in self._state.values() if st.flood_until > now)
        exhausted = sum(1 for st in self._state.values() if st.views_today >= MAX_VIEWS_PER_DAY)
        total_views = sum(st.views_today for st in self._state.values())
        return {
            "total_accounts": len(self._state),
            "flooded_now":    flooded,
            "exhausted_today": exhausted,
            "total_views_today": total_views,
        }


# singleton
VIEW_GUARD = ViewGuard()

def _load_settings_from_db():
    """تنظیمات ذخیره‌شده رو از db بخونه (بعد از import db امن است)"""
    global MAX_VIEWS_PER_DAY, MIN_GAP_SEC, MAX_GAP_SEC
    try:
        from core.db import db
        v = db.get_setting("vg_max_views_per_day", None)
        if v is not None:
            MAX_VIEWS_PER_DAY = int(v)
        mn = db.get_setting("vg_min_gap", None)
        if mn is not None:
            MIN_GAP_SEC = float(mn)
        mx = db.get_setting("vg_max_gap", None)
        if mx is not None:
            MAX_GAP_SEC = float(mx)
    except Exception:
        pass   # db هنوز آماده نیست — مقادیر پیش‌فرض استفاده میشه

# اجرای lazy — اولین بار که listener import میکنه
try:
    _load_settings_from_db()
except Exception:
    pass
