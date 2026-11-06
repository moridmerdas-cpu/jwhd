"""
قفل سشن — جلوگیری از AuthKeyDuplicated
هر سشن فقط یه کلاینت زنده داره
"""
import asyncio
from models import database as db


# قفل per-phone
_LOCKS = {}


def get_lock(phone: str) -> asyncio.Lock:
    if phone not in _LOCKS:
        _LOCKS[phone] = asyncio.Lock()
    return _LOCKS[phone]


class SessionGuard:
    """
    context manager که مطمئن می‌شه:
    - یه سشن فقط یه کلاینت زنده داره
    - قبل از استفاده جدید، قدیمی بسته می‌شه
    """

    def __init__(self, phone: str, owner: str = "unknown"):
        self.phone = phone
        self.owner = owner
        self.lock = None

    async def __aenter__(self):
        self.lock = get_lock(self.phone)
        await self.lock.acquire()
        db.debug_log("session_lock", "acquire", "OK",
                     f"{self.phone} قفل شد ({self.owner})")
        return self

    async def __aexit__(self, *args):
        db.debug_log("session_lock", "release", "OK",
                     f"{self.phone} آزاد شد ({self.owner})")
        if self.lock:
            self.lock.release()
