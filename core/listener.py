"""Listener — سرعت بالا + Purge صف"""
import asyncio, sys, random, time as _time
from pathlib import Path
from datetime import datetime, timedelta
from collections import Counter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import Config
from models import database as db
from core.engine import instant_view
from core.pool import POOL

_VIEW_PAUSED = False
_ENTITY_CACHE = {}
_PHONE_LOCKS = {}
MAX_POST_AGE = 30  # فقط پست‌های <30s
MAX_QUEUE = 20     # اگه صف >20 → پاکسازی


def set_view_paused(p):
    global _VIEW_PAUSED
    _VIEW_PAUSED = p


def is_view_paused():
    return _VIEW_PAUSED


class MultiTargetListener:
    def __init__(self, admin_phone=None, poll_interval=1, num_workers=6):
        self.admin_phone = admin_phone
        self.poll_interval = poll_interval
        self.num_workers = num_workers
        self.is_running = False
        self.client = None
        self.channel_entity = None
        self.last_msg = 0
        self.queue = asyncio.Queue(maxsize=5000)
        self.workers = []

    async def start(self):
        if not Config.AUTO_VIEW_ENABLED:
            return
        self.is_running = True
        db.debug_log("listener", "start", "OK", f"workers={self.num_workers}")

        if not POOL._initialized:
            await POOL.init()

        try:
            from core.scheduler import AccountScheduler
            s = AccountScheduler()
            s.start()
            self._scheduler = s
        except Exception as e:
            db.debug_log("listener", "scheduler", "ERROR", str(e))

        for i in range(self.num_workers):
            w = asyncio.create_task(self._worker(i))
            self.workers.append(w)

        while self.is_running:
            try:
                await self._ensure_client()
                await self._poll()
            except Exception as e:
                db.debug_log("listener", "loop", "ERROR", f"{type(e).__name__}: {e}")
                self.client = None
                self.channel_entity = None
                await asyncio.sleep(3)
                continue
            await asyncio.sleep(self.poll_interval)

    async def _ensure_client(self):
        if self.client is not None and self.client.is_connected():
            return
        for phone in POOL.all_phones:
            if phone in POOL.blacklist:
                continue
            c = await POOL.get(phone)
            if c is not None:
                self.client = c
                break
        if self.client is None:
            raise RuntimeError("no healthy account")
        target = Config.TARGET_CHANNEL_ID or Config.TARGET_CHANNEL_USERNAME
        self.channel_entity = await asyncio.wait_for(
            self.client.get_entity(target), timeout=15)
        msgs = await self.client.get_messages(self.channel_entity, limit=1)
        if msgs:
            self.last_msg = msgs[0].id
            db.debug_log("listener", "init", "OK",
                         f"channel: {self.channel_entity.title} | last: {self.last_msg}")

    async def _poll(self):
        if self.client is None or self.channel_entity is None:
            return
        msgs = await asyncio.wait_for(
            self.client.get_messages(self.channel_entity, limit=50), timeout=15)
        if not msgs:
            return
        
        # ═══ اگه صف پر شده، پاکسازی ═══
        qsize = self.queue.qsize()
        if qsize > MAX_QUEUE:
            purged = 0
            while not self.queue.empty():
                try:
                    self.queue.get_nowait()
                    self.queue.task_done()
                    purged += 1
                except asyncio.QueueEmpty:
                    break
            db.debug_log("listener", "purge", "WARN",
                         f"queue:{qsize} → purged:{purged}")
        
        new_msgs = [m for m in msgs if m.id > self.last_msg]
        if not new_msgs:
            return
        new_msgs.sort(key=lambda m: m.id)
        self.last_msg = new_msgs[-1].id
        if _VIEW_PAUSED:
            return
        for m in new_msgs:
            try:
                ts = m.date.timestamp() if m.date else _time.time()
                self.queue.put_nowait((m.id, ts))
            except asyncio.QueueFull:
                pass
        if new_msgs:
            db.debug_log("listener", "queue_add", "OK",
                         f"+{len(new_msgs)} | queue: {self.queue.qsize()}")

    async def _worker(self, wid):
        while self.is_running:
            try:
                item = await asyncio.wait_for(self.queue.get(), timeout=5)
            except asyncio.TimeoutError:
                continue
            except Exception:
                break

            msg_id, ts = item
            age = _time.time() - ts
            if age > MAX_POST_AGE:
                db.debug_log("listener", f"w{wid}", "SKIP",
                             f"ID={msg_id} age={age:.0f}s")
                self.queue.task_done()
                continue

            # ═══ هر worker تمام شیفت فعال ═══
            phones = list(POOL.active_phones())

            try:
                await self._view_message(msg_id, phones, wid)
            except Exception as e:
                db.debug_log("listener", f"w{wid}", "ERROR", str(e))
            finally:
                try:
                    self.queue.task_done()
                except Exception:
                    pass

    async def _view_one(self, phone, msg_id):
        # Lock per phone
        lock = _PHONE_LOCKS.get(phone)
        if lock is None:
            lock = asyncio.Lock()
            _PHONE_LOCKS[phone] = lock

        async with lock:
            try:
                c = POOL.clients.get(phone)
                if c is None or not c.is_connected():
                    c = await POOL.get(phone)
                    if c is None:
                        return ("NO_CLI", phone)
                target = Config.TARGET_CHANNEL_ID or Config.TARGET_CHANNEL_USERNAME
                key = (phone, str(target))
                ent = _ENTITY_CACHE.get(key)
                if ent is None:
                    try:
                        ent = await asyncio.wait_for(c.get_entity(target), timeout=10)
                        _ENTITY_CACHE[key] = ent
                    except Exception as e:
                        return (f"ENT:{type(e).__name__}", phone)
                try:
                    r = await asyncio.wait_for(
                        instant_view(c, ent, [msg_id]), timeout=10)
                except asyncio.TimeoutError:
                    return ("V_TIMEOUT", phone)
                except Exception as e:
                    return (f"V:{type(e).__name__}", phone)
                if r.get("ok"):
                    return ("OK", phone)
                elif "flood" in r:
                    u = (datetime.utcnow() + timedelta(seconds=r["flood"])).isoformat()
                    db.update_account_status(phone, "flood", r["error"], u)
                    return (f"FLOOD:{r['flood']}", phone)
                else:
                    return (f"E:{str(r.get('error',''))[:20]}", phone)
            except Exception as e:
                return (f"OUT:{type(e).__name__}", phone)

    async def _view_message(self, msg_id, phones, wid):
        if not phones:
            return
        random.shuffle(phones)
        n = len(phones)
        window = random.uniform(2.0, 3.5)
        t0 = _time.time()

        async def one(phone, delay):
            if delay > 0:
                await asyncio.sleep(delay)
            return await self._view_one(phone, msg_id)

        tasks = []
        for i, phone in enumerate(phones):
            d = (i / max(n, 1)) * window + random.uniform(0, 0.2)
            tasks.append(asyncio.create_task(one(phone, d)))

        try:
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=window + 10)
        except asyncio.TimeoutError:
            results = []
            for t in tasks:
                if not t.done():
                    t.cancel()

        reasons = Counter()
        suc = 0
        for r in results:
            if isinstance(r, tuple) and r:
                reason = r[0]
                reasons[reason] = reasons.get(reason, 0) + 1
                if reason == "OK":
                    suc += 1
        elapsed = _time.time() - t0
        summary = " | ".join(f"{k}={v}" for k, v in reasons.most_common(5))
        db.debug_log("listener", "view_done", "RESULT",
                     f"ID={msg_id} | w{wid} | {suc}/{n} | {elapsed:.1f}s | {summary} | q:{self.queue.qsize()}")

    async def stop(self):
        self.is_running = False
        for w in self.workers:
            w.cancel()


class ChannelListener(MultiTargetListener):
    pass


# ═══════════════════════════════════════════════════════
#  GroupListener — ReadHistory روی گروه مستقل
# ═══════════════════════════════════════════════════════

_GROUP_ENTITY_CACHE = {}
_GROUP_PHONE_LOCKS  = {}


class GroupListener:
    """هر پیام جدید در گروه رو با ReadHistory می‌خونه — با تمام اکانت‌های شیفت فعال"""

    MAX_GROUP_MSG_AGE = 60   # ثانیه — پیام‌های قدیمی‌تر skip می‌شن
    MAX_GROUP_QUEUE   = 50
    POLL_INTERVAL     = 1.5  # ثانیه بین هر poll

    def __init__(self, num_workers: int = 4):
        self.num_workers   = num_workers
        self.is_running    = False
        self.client        = None
        self.group_entity  = None
        self.last_msg_id   = 0
        self.queue         = asyncio.Queue(maxsize=5000)
        self.workers: list = []

    # ───────────────── entry ─────────────────
    async def start(self):
        if not Config.TARGET_GROUP_ID:
            db.debug_log("group_listener", "start", "SKIP",
                         "TARGET_GROUP_ID تنظیم نشده")
            return

        self.is_running = True
        db.debug_log("group_listener", "start", "OK",
                     f"group={Config.TARGET_GROUP_ID} | workers={self.num_workers}")

        if not POOL._initialized:
            await POOL.init()

        for i in range(self.num_workers):
            self.workers.append(asyncio.create_task(self._worker(i)))

        while self.is_running:
            try:
                await self._ensure_client()
                await self._poll()
            except Exception as e:
                db.debug_log("group_listener", "loop", "ERROR",
                             f"{type(e).__name__}: {e}")
                self.client       = None
                self.group_entity = None
                await asyncio.sleep(5)
                continue
            await asyncio.sleep(self.POLL_INTERVAL)

    # ───────────────── ensure client ─────────────────
    async def _ensure_client(self):
        if self.client is not None and self.client.is_connected():
            return
        for phone in POOL.all_phones:
            if phone in POOL.blacklist:
                continue
            c = await POOL.get(phone)
            if c is not None:
                self.client = c
                break
        if self.client is None:
            raise RuntimeError("no healthy account for group listener")

        self.group_entity = await asyncio.wait_for(
            self.client.get_entity(Config.TARGET_GROUP_ID), timeout=15)

        msgs = await self.client.get_messages(self.group_entity, limit=1)
        if msgs:
            self.last_msg_id = msgs[0].id
        db.debug_log("group_listener", "init", "OK",
                     f"group: {self.group_entity.title} | last: {self.last_msg_id}")

    # ───────────────── poll ─────────────────
    async def _poll(self):
        if self.client is None or self.group_entity is None:
            return

        msgs = await asyncio.wait_for(
            self.client.get_messages(self.group_entity, limit=50), timeout=15)
        if not msgs:
            return

        # پاکسازی صف اگه پر شده
        qsize = self.queue.qsize()
        if qsize > self.MAX_GROUP_QUEUE:
            purged = 0
            while not self.queue.empty():
                try:
                    self.queue.get_nowait()
                    self.queue.task_done()
                    purged += 1
                except asyncio.QueueEmpty:
                    break
            db.debug_log("group_listener", "purge", "WARN",
                         f"queue:{qsize} → purged:{purged}")

        new_msgs = [m for m in msgs if m.id > self.last_msg_id]
        if not new_msgs:
            return
        new_msgs.sort(key=lambda m: m.id)
        self.last_msg_id = new_msgs[-1].id

        if _VIEW_PAUSED:
            return

        for m in new_msgs:
            ts = m.date.timestamp() if m.date else _time.time()
            try:
                self.queue.put_nowait((m.id, ts))
            except asyncio.QueueFull:
                pass

        db.debug_log("group_listener", "queue_add", "OK",
                     f"+{len(new_msgs)} | queue: {self.queue.qsize()}")

    # ───────────────── worker ─────────────────
    async def _worker(self, wid: int):
        while self.is_running:
            try:
                item = await asyncio.wait_for(self.queue.get(), timeout=5)
            except asyncio.TimeoutError:
                continue
            except Exception:
                break

            msg_id, ts = item
            age = _time.time() - ts
            if age > self.MAX_GROUP_MSG_AGE:
                db.debug_log("group_listener", f"w{wid}", "SKIP",
                             f"ID={msg_id} age={age:.0f}s")
                self.queue.task_done()
                continue

            phones = list(POOL.active_phones())
            try:
                await self._read_message(msg_id, phones, wid)
            except Exception as e:
                db.debug_log("group_listener", f"w{wid}", "ERROR", str(e))
            finally:
                try:
                    self.queue.task_done()
                except Exception:
                    pass

    # ───────────────── read one phone ─────────────────
    async def _read_one(self, phone: str, msg_id: int):
        lock = _GROUP_PHONE_LOCKS.setdefault(phone, asyncio.Lock())
        async with lock:
            try:
                c = POOL.clients.get(phone)
                if c is None or not c.is_connected():
                    c = await POOL.get(phone)
                    if c is None:
                        return ("NO_CLI", phone)

                key = (phone, str(Config.TARGET_GROUP_ID))
                ent = _GROUP_ENTITY_CACHE.get(key)
                if ent is None:
                    try:
                        ent = await asyncio.wait_for(
                            c.get_entity(Config.TARGET_GROUP_ID), timeout=10)
                        _GROUP_ENTITY_CACHE[key] = ent
                    except Exception as e:
                        return (f"ENT:{type(e).__name__}", phone)

                try:
                    from core.engine import instant_read
                    r = await asyncio.wait_for(instant_read(c, ent), timeout=10)
                except asyncio.TimeoutError:
                    return ("R_TIMEOUT", phone)
                except Exception as e:
                    return (f"R:{type(e).__name__}", phone)

                if r.get("ok"):
                    return ("OK", phone)
                elif "flood" in r:
                    from datetime import datetime, timedelta
                    u = (datetime.utcnow() + timedelta(seconds=r["flood"])).isoformat()
                    db.update_account_status(phone, "flood", r["error"], u)
                    return (f"FLOOD:{r['flood']}", phone)
                else:
                    return (f"E:{str(r.get('error', ''))[:20]}", phone)
            except Exception as e:
                return (f"OUT:{type(e).__name__}", phone)

    # ───────────────── read all phones ─────────────────
    async def _read_message(self, msg_id: int, phones: list, wid: int):
        if not phones:
            return
        random.shuffle(phones)
        n      = len(phones)
        window = random.uniform(1.5, 2.5)
        t0     = _time.time()

        async def one(phone, delay):
            if delay > 0:
                await asyncio.sleep(delay)
            return await self._read_one(phone, msg_id)

        tasks = [
            asyncio.create_task(
                one(phone, (i / max(n, 1)) * window + random.uniform(0, 0.15))
            )
            for i, phone in enumerate(phones)
        ]

        try:
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=window + 10)
        except asyncio.TimeoutError:
            results = []
            for t in tasks:
                if not t.done():
                    t.cancel()

        from collections import Counter
        reasons = Counter()
        suc = 0
        for r in results:
            if isinstance(r, tuple) and r:
                reason = r[0]
                reasons[reason] += 1
                if reason == "OK":
                    suc += 1

        elapsed = _time.time() - t0
        summary = " | ".join(f"{k}={v}" for k, v in reasons.most_common(5))
        db.debug_log("group_listener", "read_done", "RESULT",
                     f"ID={msg_id} | w{wid} | {suc}/{n} | {elapsed:.1f}s | {summary} | q:{self.queue.qsize()}")

    # ───────────────── stop ─────────────────
    async def stop(self):
        self.is_running = False
        for w in self.workers:
            w.cancel()
