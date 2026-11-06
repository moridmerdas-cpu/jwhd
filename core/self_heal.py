"""
سیستم خودترمیم کامل
- اسکن خودکار IPها
- مخزن زاپاس
- swap لحظه‌ای flood/error
"""
import asyncio
import subprocess
import shutil
import json
import time
import random
from pathlib import Path
from datetime import datetime, timedelta

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import Config
from models import database as db
from core.warp_pool import (
    POOL_DIR, get_all_configs, get_port_from_conf,
    remove_config, generate_one, find_free_slot, _existing_keys,
    ENDPOINTS, _fetch_config, _parse
)


HEALTHY_FILE = Config.BASE_DIR / "proxies" / "healthy_ports.json"
TARGET_HEALTHY = 50     # حداقل پورت سالم که می‌خوایم همیشه داشته باشیم
TARGET_SPARE = 15       # تعداد پورت‌های زاپاس اضافی


class SelfHealGuardian:
    """نگهبان کامل سیستم"""

    def __init__(self, check_interval: int = 60):
        self.check_interval = check_interval
        self.running = False
        self._lock = asyncio.Lock()

    async def start(self):
        self.running = True
        db.debug_log("self_heal", "start", "OK",
                     f"🛡️ نگهبان خودترمیم روشن | چک هر {self.check_interval}s")
        await asyncio.sleep(20)

        # حلقه اصلی
        cycle = 0
        while self.running:
            cycle += 1
            try:
                # هر بار: سلامت + ترمیم
                await self._full_cycle(cycle)
            except Exception as e:
                db.debug_log("self_heal", "loop", "ERROR", f"{type(e).__name__}: {e}")
            await asyncio.sleep(self.check_interval)

    async def _full_cycle(self, cycle):
        """یه چرخه کامل: اسکن → ترمیم → swap"""
        async with self._lock:
            db.debug_log("self_heal", "cycle", "START", f"چرخه {cycle}")

            # ۱. اسکن IPهای فعلی
            await self._scan_and_save()

            # ۲. اگه پورت‌های سالم کم بود، کانفیگ جدید بساز
            await self._ensure_spare_pool()

            # ۳. اکانت‌های flood/error رو ترمیم کن
            await self._heal_accounts()

            # ۴. wireproxyهای مرده رو راه‌اندازی مجدد
            await self._restart_dead_proxies()

            db.debug_log("self_heal", "cycle", "DONE", f"چرخه {cycle} تموم")

    async def _scan_and_save(self):
        """اسکن همه پورت‌ها و ذخیره پورت‌های سالم"""
        configs = get_all_configs()
        if not configs:
            return

        sem = asyncio.Semaphore(30)
        tasks = [self._test_port(get_port_from_conf(c), sem) for c in configs]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        ip_to_ports = {}
        healthy = 0
        for r in results:
            if isinstance(r, tuple) and r[1]:
                port, ip = r
                ip_to_ports.setdefault(ip, []).append(port)
                healthy += 1

        data = {
            "ips": list(ip_to_ports.keys()),
            "ip_to_ports": ip_to_ports,
            "port_to_ip": {str(p): ip for ip, ports in ip_to_ports.items() for p in ports},
            "updated_at": datetime.now().isoformat(),
        }
        HEALTHY_FILE.write_text(json.dumps(data, indent=2))

        # reload cache engine
        try:
            from core.engine import reload_healthy
            reload_healthy()
        except Exception:
            pass

        db.debug_log("self_heal", "scan", "OK",
                     f"✅ {healthy} پورت سالم | {len(ip_to_ports)} IP یکتا")
        return healthy

    async def _test_port(self, port, sem):
        if not port:
            return (port, "")
        async with sem:
            try:
                proc = await asyncio.create_subprocess_exec(
                    "curl", "-s", "--max-time", "6",
                    "-x", f"socks5h://127.0.0.1:{port}",
                    "https://api.ipify.org",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL
                )
                try:
                    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=9)
                    return (port, stdout.decode().strip())
                except asyncio.TimeoutError:
                    proc.kill()
                    return (port, "")
            except Exception:
                return (port, "")

    async def _ensure_spare_pool(self):
        """حذف کانفیگ‌های خراب و تولید جدید"""
        configs = get_all_configs()
        healthy_ports = set()
        if HEALTHY_FILE.exists():
            try:
                data = json.loads(HEALTHY_FILE.read_text())
                healthy_ports = set(int(p) for p in data.get("port_to_ip", {}).keys())
            except Exception:
                pass

        # پیدا کردن کانفیگ‌های خراب
        dead_configs = []
        for conf in configs:
            port = get_port_from_conf(conf)
            if port and port not in healthy_ports:
                dead_configs.append(conf)

        db.debug_log("self_heal", "spare", "INFO",
                     f"سالم {len(healthy_ports)} | خراب {len(dead_configs)} | کل {len(configs)}")

        # اگه تعداد سالم کافیه، کاری نکن
        if len(healthy_ports) >= TARGET_HEALTHY:
            return

        needed = TARGET_HEALTHY - len(healthy_ports)
        db.debug_log("self_heal", "spare", "GEN", f"نیاز به {needed} کانفیگ جدید")

        # حذف کانفیگ‌های خراب
        for conf in dead_configs[:needed]:
            try:
                # کشتن wireproxy مربوطه
                pkill = shutil.which("pkill") or "/usr/bin/pkill"
                subprocess.run([pkill, "-f", f"wireproxy.*{conf}"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                remove_config(conf)
            except Exception:
                pass

        # ساخت جدید
        existing_keys = _existing_keys()
        for _ in range(needed):
            slot = find_free_slot()
            if slot == 0:
                break
            ok = await asyncio.get_event_loop().run_in_executor(
                None, generate_one, slot, existing_keys, 10
            )
            if ok:
                self._start_wireproxy_slot(slot)
            await asyncio.sleep(5)


    async def _heal_accounts(self):
        """اکانت‌های flood/error رو ترمیم کن"""
        accounts = db.get_all_accounts()

        for acc in accounts:
            if acc["status"] not in ("flood", "error"):
                continue

            phone = acc["phone"]
            # چک کن flood_until تموم شده
            if acc["status"] == "flood" and acc.get("flood_until"):
                try:
                    until = datetime.fromisoformat(acc["flood_until"])
                    if until < datetime.utcnow():
                        db.update_account_status(phone, "idle")
                        db.debug_log("self_heal", "heal", "OK",
                                     f"{phone}: flood تموم شد → idle")
                        continue
                except Exception:
                    pass

            # اگه error هست، try جدید بزن
            if acc["status"] == "error":
                # با WARP جدید تست کن
                await self._retry_account(phone)

    async def _retry_account(self, phone):
        """تلاش مجدد برای یه اکانت با WARP متفاوت"""
        try:
            from core.engine import make_client, health_check
            ss = db.get_session(phone)
            if not ss:
                return
            client = make_client(ss, phone=phone + "_retry")  # hash متفاوت → IP متفاوت
            await asyncio.wait_for(client.connect(), timeout=20)
            h = await health_check(client)
            await client.disconnect()
            if h["status"] == "ok":
                db.update_account_status(phone, "idle")
                db.debug_log("self_heal", "retry", "OK", f"{phone} → idle")
        except Exception as e:
            db.debug_log("self_heal", "retry", "WARN", f"{phone}: {type(e).__name__}")

    async def _restart_dead_proxies(self):
        """wireproxyهای مرده رو دوباره راه‌اندازی کن"""
        started = 0
        for conf in get_all_configs():
            if not self._is_running(conf):
                self._start_wireproxy_by_path(conf)
                started += 1
        if started > 0:
            db.debug_log("self_heal", "restart", "OK", f"{started} wireproxy راه‌اندازی مجدد")

    def _is_running(self, conf):
        try:
            pgrep = shutil.which("pgrep") or "/usr/bin/pgrep"
            r = subprocess.run([pgrep, "-f", f"wireproxy.*{conf}"],
                               capture_output=True, timeout=3)
            return r.returncode == 0
        except Exception:
            return False

    def _start_wireproxy_slot(self, slot):
        conf = POOL_DIR / f"warp_{slot:03d}.conf"
        self._start_wireproxy_by_path(conf)

    def _start_wireproxy_by_path(self, conf):
        if not conf.exists():
            return
        log = POOL_DIR / f"{conf.stem}.log"
        pkill = shutil.which("pkill") or "/usr/bin/pkill"
        subprocess.run([pkill, "-f", f"wireproxy.*{conf}"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.2)
        subprocess.Popen(
            ["wireproxy", "--config", str(conf)],
            stdout=open(log, "a"), stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    def stop(self):
        self.running = False
        db.debug_log("self_heal", "stop", "OK", "نگهبان متوقف")


async def _test():
    db.init_db()
    g = SelfHealGuardian(check_interval=60)
    print("🧪 تست self_heal")
    await g._scan_and_save()
    print("✅ تست تموم")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        asyncio.run(_test())
    else:
        db.init_db()
        asyncio.run(SelfHealGuardian().start())
