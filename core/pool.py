"""Pool — 118 اکانت، 4 شیفت مساوی، همیشه متصل"""
import asyncio
import random
import time as _time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import Config
from models import database as db
from core.engine import make_client


class _RateLimiter:
    def __init__(self):
        self._cooldown = {}
    def allow(self, phone):
        return _time.time() >= self._cooldown.get(phone, 0)
    def reward(self, phone):
        self._cooldown[phone] = _time.time() + random.uniform(0.8, 1.5)
    def penalty(self, phone, seconds):
        self._cooldown[phone] = _time.time() + max(seconds, 1.0)


RATE = _RateLimiter()


class ClientPool:
    def __init__(self):
        self.clients = {}
        self.all_phones = []
        self.shifts = {1: [], 2: [], 3: [], 4: []}
        self.active_shift = 1
        self.lock = asyncio.Lock()
        self._initialized = False
        self.blacklist = set()

    async def init(self):
        if self._initialized:
            return
        async with self.lock:
            if self._initialized:
                return
            self._initialized = True

            accounts = db.get_all_accounts()
            # ═══ Skip dead accounts ═══
            accounts = [a for a in accounts if a.get("status") != "dead"]
            if not accounts:
                return

            phones = [a["phone"] for a in accounts]
            random.shuffle(phones)
            n = len(phones)
            base = n // 4
            extra = n % 4
            self.all_phones = phones
            start = 0
            for i in range(4):
                size = base + (1 if i < extra else 0)
                self.shifts[i + 1] = phones[start:start + size]
                start += size

            db.debug_log("pool", "init", "OK",
                         f"total:{n} " + " ".join(f"S{k}:{len(v)}" for k, v in self.shifts.items()))

            # اتصال موازی همه
            sem = asyncio.Semaphore(20)
            ok = [0]
            async def one(p):
                async with sem:
                    r = await self._connect_one(p)
                    if r:
                        ok[0] += 1
            tasks = [asyncio.create_task(one(p)) for p in phones]
            await asyncio.gather(*tasks, return_exceptions=True)
            db.debug_log("pool", "init", "DONE", f"connected:{ok[0]}/{n}")

    async def _connect_one(self, phone):
        if phone in self.blacklist:
            return None
        c = self.clients.get(phone)
        if c is not None and c.is_connected():
            return c
        ss = db.get_session(phone)
        if not ss:
            self.blacklist.add(phone)
            return None
        try:
            client = make_client(ss, phone=phone)
            await asyncio.wait_for(client.connect(), timeout=25)
            ok = await asyncio.wait_for(client.is_user_authorized(), timeout=10)
            if not ok:
                await client.disconnect()
                return None
            self.clients[phone] = client
            return client
        except Exception:
            self.blacklist.add(phone)
            return None

    async def get(self, phone):
        c = self.clients.get(phone)
        if c is not None and c.is_connected():
            return c
        return await self._connect_one(phone)

    def active_phones(self):
        return self.shifts.get(self.active_shift, [])

    def swap_cycle(self):
        self.active_shift = (self.active_shift % 4) + 1
        return self.active_shift

    async def drop(self, phone):
        c = self.clients.pop(phone, None)
        if c:
            try:
                await c.disconnect()
            except Exception:
                pass

    async def close_all(self):
        for c in self.clients.values():
            try:
                await c.disconnect()
            except Exception:
                pass
        self.clients.clear()


POOL = ClientPool()
