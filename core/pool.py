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
        self.blacklist = set()          # فقط اکانت‌های بدون session
        self.errors = {}                # phone -> آخرین دلیل شکست اتصال
        self._retry_after = {}          # phone -> زمانی که اجازه تلاش مجدد داریم
        self._bg = set()
        self.ready = asyncio.Event()    # بعد از پایان init ست میشه

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

            # شیفت‌ها از ستون shift دیتابیس خونده میشن تا لیست اکانت‌ها با pool یکی باشه
            buckets = {1: [], 2: [], 3: [], 4: []}
            for a in accounts:
                sh = str(a.get("shift") or "")
                if sh in ("1", "2", "3", "4"):
                    buckets[int(sh)].append(a["phone"])
            for a in accounts:
                if not any(a["phone"] in v for v in buckets.values()):
                    k = min(buckets, key=lambda x: len(buckets[x]))
                    buckets[k].append(a["phone"])
                    db.update_account_shift(a["phone"], str(k))
            self.shifts = buckets
            phones = [p for v in buckets.values() for p in v]
            n = len(phones)
            self.all_phones = phones
            try:
                self.active_shift = int(db.get_setting("active_shift", 1) or 1)
                if self.active_shift not in buckets:
                    self.active_shift = 1
            except Exception:
                self.active_shift = 1

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
            await asyncio.to_thread(self._safe_sync)

    async def _connect_one(self, phone, force=False):
        if phone in self.blacklist:
            return None
        c = self.clients.get(phone)
        if c is not None and c.is_connected():
            return c
        now = _time.time()
        if not force and self._retry_after.get(phone, 0) > now:
            return None
        try:
            ss = db.get_session(phone)
            if not ss:
                self.blacklist.add(phone)
                raise RuntimeError("session خالیه")
            client = make_client(ss, phone=phone)
            await asyncio.wait_for(client.connect(), timeout=25)
            ok = await asyncio.wait_for(client.is_user_authorized(), timeout=10)
            if not ok:
                await client.disconnect()
                raise RuntimeError("session معتبر نیست (unauthorized)")
            self.clients[phone] = client
            self._retry_after.pop(phone, None)
            if self.errors.pop(phone, None) is not None:
                db.update_account_status(phone, "idle", None)
            return client
        except Exception as e:
            reason = f"{type(e).__name__}: {str(e)[:120]}"
            if type(e).__name__ == "InvalidToken":
                reason = "InvalidToken: ENCRYPTION_KEY با کلید زمان ذخیره‌ی session فرق داره"
            self.errors[phone] = reason
            self._retry_after[phone] = now + 90
            db.debug_log("pool", "connect", "ERROR", f"{phone}: {reason}")
            try:
                db.update_account_status(phone, "error", reason)
            except Exception:
                pass
            return None

    async def ensure_connected(self, phones, force=False, limit=10):
        sem = asyncio.Semaphore(limit)

        async def one(p):
            async with sem:
                c = self.clients.get(p)
                if c is not None and c.is_connected():
                    return
                await self._connect_one(p, force=force)

        await asyncio.gather(*(one(p) for p in phones), return_exceptions=True)

    async def activate_shift(self, shift):
        """شیفت رو فعال می‌کنه، اکانت‌هاش رو واقعاً وصل می‌کنه، وضعیت‌ها رو sync می‌کنه و گزارش می‌ده."""
        self.active_shift = shift
        phones = list(self.shifts.get(shift, []))
        await self.ensure_connected(phones, force=True)
        await asyncio.to_thread(self._safe_sync)
        live = [p for p in phones if self._is_live(p)]
        return {
            "total": len(phones),
            "connected": len(live),
            "errors": {p: self.errors[p] for p in phones if p in self.errors},
        }

    def _is_live(self, phone):
        c = self.clients.get(phone)
        return c is not None and c.is_connected()

    async def get(self, phone):
        c = self.clients.get(phone)
        if c is not None and c.is_connected():
            return c
        return await self._connect_one(phone)

    def active_phones(self):
        return self.shifts.get(self.active_shift, [])

    def swap_cycle(self):
        self.active_shift = (self.active_shift % 4) + 1
        self.request_status_sync()
        return self.active_shift

    def sync_status(self):
        """اکانت‌های متصلِ شیفت فعال = online، بقیه = idle (استراحت). flood/error دست نمی‌خوره."""
        on  = [p for p in self.shifts.get(self.active_shift, []) if self._is_live(p)]
        off = [p for p in self.all_phones if p not in on]
        db.set_status_bulk(on, "online")
        db.set_status_bulk(off, "idle")
        db.debug_log("pool", "sync", "OK",
                     f"shift={self.active_shift} online={len(on)} idle={len(off)}")

    def _safe_sync(self):
        try:
            self.sync_status()
        except Exception as e:
            db.debug_log("pool", "sync", "ERROR", f"{type(e).__name__}: {e}")

    def request_status_sync(self):
        async def job():
            try:
                await self.ensure_connected(self.shifts.get(self.active_shift, []))
                await asyncio.to_thread(self._safe_sync)
            except Exception as e:
                db.debug_log("pool", "sync_job", "ERROR", f"{type(e).__name__}: {e}")
        try:
            t = asyncio.get_running_loop().create_task(job())
            self._bg.add(t)
            t.add_done_callback(self._bg.discard)
        except RuntimeError:
            pass

    async def add_account_live(self, phone):
        """اکانت تازه اضافه‌شده رو بر اساس شیفت دیتابیس وارد pool می‌کنه و وصلش می‌کنه."""
        try:
            await asyncio.wait_for(self.ready.wait(), timeout=30)
        except asyncio.TimeoutError:
            pass
        row = db.get_account(phone)
        sh = int(str((row or {}).get("shift") or 1))
        sh = sh if sh in self.shifts else 1
        self.blacklist.discard(phone)
        if phone not in self.all_phones:
            self.all_phones.append(phone)
        for v in self.shifts.values():
            if phone in v:
                v.remove(phone)
        self.shifts[sh].append(phone)
        client = await self._connect_one(phone, force=True)
        await asyncio.to_thread(self._safe_sync)
        return client

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
