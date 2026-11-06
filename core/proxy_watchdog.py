"""
نگهبان پروکسی‌ها v2
- بار اول: به همه اکانت‌ها پورت سالم تخصیص می‌ده
- هر ۳۰s: چک می‌کنه، اگه مرده بود سوییچ می‌کنه
- IPهای جدید رو کشف می‌کنه
"""
import asyncio
import hashlib
import json
import random
import subprocess
import time
from pathlib import Path
from datetime import datetime

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import Config
from models import database as db
from core.warp_pool import (
    POOL_DIR, get_all_configs, get_port_from_conf,
    generate_one, find_free_slot, _existing_keys,
)


HEALTHY_FILE = Config.BASE_DIR / "proxies" / "healthy_ports.json"
ACCOUNT_PROXY_FILE = Config.BASE_DIR / "proxies" / "account_proxy.json"

ACCOUNT_PROXY = {}


def _load_account_proxy():
    global ACCOUNT_PROXY
    if ACCOUNT_PROXY_FILE.exists():
        try:
            ACCOUNT_PROXY = json.loads(ACCOUNT_PROXY_FILE.read_text())
            return
        except Exception:
            pass
    ACCOUNT_PROXY = {}


def _save_account_proxy():
    try:
        ACCOUNT_PROXY_FILE.write_text(json.dumps(ACCOUNT_PROXY, indent=2))
    except Exception as e:
        db.debug_log("watchdog", "save", "ERROR", f"{e}")


def _load_healthy():
    if HEALTHY_FILE.exists():
        try:
            return json.loads(HEALTHY_FILE.read_text())
        except Exception:
            pass
    return {"ips": [], "ip_to_ports": {}, "port_to_ip": {}}


def _choose_port(phone, healthy, exclude_ports=None):
    """
    انتخاب پورت سالم — توزیع یکنواخت بین IPها
    هر IP به اندازه سهمش (تعداد پورت / کل) انتخاب می‌شه
    """
    ips = healthy.get("ips", [])
    ip_to_ports = healthy.get("ip_to_ports", {})
    if not ips:
        return None
    exclude_ports = exclude_ports or set()

    # مرتب‌سازی IPها بر اساس تعداد پورت (کم به زیاد)
    # تا IPهای کم‌پورت اول انتخاب بشن
    sorted_ips = sorted(ips, key=lambda ip: len(ip_to_ports.get(ip, [])))

    h = int(hashlib.md5(phone.encode()).hexdigest(), 16)

    # رندوم انتخاب IP
    # ولی IP با پورت کمتر، شانس بیشتری می‌گیره
    # اینطوری توزیع بین IPها متوازن می‌شه
    random.seed(h)
    chosen_ip = random.choice(sorted_ips)

    ports = ip_to_ports.get(chosen_ip, [])
    if not ports:
        return None

    # سعی کن از این IP پورت آزاد بگیر
    start = h % len(ports)
    for i in range(len(ports)):
        candidate = ports[(start + i) % len(ports)]
        if candidate not in exclude_ports:
            return candidate, chosen_ip

    # اگه همه پر بود، برو سراغ IP بعدی
    for ip in sorted_ips:
        if ip == chosen_ip:
            continue
        ports = ip_to_ports.get(ip, [])
        for p in ports:
            if p not in exclude_ports:
                return p, ip

    return None


class ProxyWatchdog:
    def __init__(self, check_interval=30):
        self.check_interval = check_interval
        self.running = False
        self._known_ips = set()

    async def start(self):
        self.running = True
        _load_account_proxy()
        db.debug_log("watchdog", "start", "OK",
                     f"🩺 Watchdog v2 | چک هر {self.check_interval}s | {len(ACCOUNT_PROXY)} تخصیص قبلی")
        await asyncio.sleep(15)

        while self.running:
            try:
                await self._cycle()
            except Exception as e:
                db.debug_log("watchdog", "loop", "ERROR", f"{type(e).__name__}: {e}")
            await asyncio.sleep(self.check_interval)

    async def _cycle(self):
        # ۱. اسکن healthy
        healthy = await self._scan_healthy()
        if not healthy:
            db.debug_log("watchdog", "cycle", "WARN", "هیچ پورت سالمی نیست")
            return

        healthy_ports = set(p for p, _ in healthy)

        # ۲. تخصیص به اکانت‌های بدون پورت
        await self._assign_new(healthy)

        # ۳. سوییچ اکانت‌های خراب
        await self._fix_dead(healthy_ports, healthy)

        # ۴. اگه پورت سالم کم بود، بساز
        if len(healthy) < 30:
            needed = 30 - len(healthy)
            db.debug_log("watchdog", "regen", "INFO", f"نیاز به {needed} کانفیگ")
            asyncio.create_task(self._generate_new(needed))

        db.debug_log("watchdog", "cycle", "OK",
                     f"✅ {len(healthy)} سالم | {len(ACCOUNT_PROXY)} تخصیص")

    async def _scan_healthy(self):
        configs = get_all_configs()
        sem = asyncio.Semaphore(30)
        tasks = [self._test_port(get_port_from_conf(c), sem) for c in configs]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        ip_to_ports = {}
        for r in results:
            if isinstance(r, tuple) and r[1]:
                port, ip = r
                ip_to_ports.setdefault(ip, []).append(port)

        data = {
            "ips": sorted(ip_to_ports.keys()),
            "ip_to_ports": ip_to_ports,
            "port_to_ip": {str(p): ip for ip, ports in ip_to_ports.items() for p in ports},
            "updated_at": datetime.now().isoformat(),
        }
        HEALTHY_FILE.write_text(json.dumps(data, indent=2))

        try:
            from core.engine import reload_healthy
            reload_healthy()
        except Exception:
            pass

        # تشخیص IP جدید
        current_ips = set(ip_to_ports.keys())
        new_ips = current_ips - self._known_ips
        if new_ips and self._known_ips:
            db.debug_log("watchdog", "new_ip", "OK",
                         f"🎉 {len(new_ips)} IP جدید")
        self._known_ips = current_ips

        return [(p, ip) for ip, ports in ip_to_ports.items() for p in ports]

    async def _test_port(self, port, sem):
        if not port:
            return (port, "")
        async with sem:
            # اول چک سریع اینکه پورت بازه (socket)
            import socket
            def quick_check():
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=1.5):
                        return True
                except Exception:
                    return False
            is_open = await asyncio.get_event_loop().run_in_executor(None, quick_check)
            if not is_open:
                return (port, "")

            # بعد curl برای چک IP
            try:
                proc = await asyncio.create_subprocess_exec(
                    "curl", "-s", "--max-time", "5",
                    "-x", f"socks5h://127.0.0.1:{port}",
                    "https://api.ipify.org",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                try:
                    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=7)
                    return (port, stdout.decode().strip())
                except asyncio.TimeoutError:
                    proc.kill()
                    return (port, "")
            except Exception:
                return (port, "")

    async def _assign_new(self, healthy):
        """به اکانت‌های بدون پورت، پورت تخصیص بده (بدون تکرار)"""
        accounts = db.get_all_accounts()
        assigned = 0
        # پورت‌های در استفاده
        used_ports = set(info.get("port") for info in ACCOUNT_PROXY.values())

        for a in accounts:
            phone = a["phone"]
            if phone in ACCOUNT_PROXY:
                continue
            result = _choose_port(phone, _load_healthy(), exclude_ports=used_ports)
            if result:
                port, ip = result
                ACCOUNT_PROXY[phone] = {
                    "port": port, "ip": ip,
                    "assigned_at": datetime.now().isoformat(),
                }
                used_ports.add(port)
                assigned += 1

        if assigned:
            _save_account_proxy()
            db.debug_log("watchdog", "assign", "OK",
                         f"✅ {assigned} اکانت پورت گرفت")

    async def _fix_dead(self, healthy_ports, healthy):
        """سوییچ اکانت‌های پورت‌مرده"""
        fixed = 0
        for phone, info in list(ACCOUNT_PROXY.items()):
            cur_port = info.get("port", 0)
            if cur_port not in healthy_ports:
                result = _choose_port(phone + "_fix", _load_healthy())
                if result:
                    port, ip = result
                    ACCOUNT_PROXY[phone] = {
                        "port": port, "ip": ip,
                        "fixed_at": datetime.now().isoformat(),
                    }
                    fixed += 1
                    db.debug_log("watchdog", "fix", "OK",
                                 f"{phone}: {cur_port} → {port}")

        if fixed:
            _save_account_proxy()
            # ریست pool — با احتیاط
            try:
                from core.pool import POOL
                from core.session_lock import get_lock

                # فقط clientهایی که WARPشون عوض شده رو ببند
                for phone in ACCOUNT_PROXY.keys():
                    if phone not in POOL.clients:
                        continue
                    # اگه WARP عوض شده
                    info = ACCOUNT_PROXY[phone]
                    cur_port = info.get("port", 0)
                    # اگه پورت جدید متفاوته، کلاینت قدیمی رو ببند
                    try:
                        async with get_lock(phone):
                            c = POOL.clients.pop(phone, None)
                            if c:
                                try:
                                    await c.disconnect()
                                except Exception:
                                    pass
                                await asyncio.sleep(0.5)
                    except Exception:
                        pass

                db.debug_log("watchdog", "reset", "OK",
                             f"{fixed} اکانت ریست — قبل از reconnect")
            except Exception as e:
                db.debug_log("watchdog", "reset", "ERROR", str(e))

    async def _generate_new(self, count):
        existing = _existing_keys()
        for _ in range(count):
            slot = find_free_slot()
            if slot == 0:
                break
            ok = await asyncio.get_event_loop().run_in_executor(
                None, generate_one, slot, existing, 10
            )
            if ok:
                conf = POOL_DIR / f"warp_{slot:03d}.conf"
                self._start_wireproxy(conf)
            await asyncio.sleep(3)

    def _start_wireproxy(self, conf):
        if not conf.exists():
            return
        log = POOL_DIR / f"{conf.stem}.log"
        subprocess.run(["/usr/bin/pkill", "-f", f"wireproxy.*{conf}"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.3)
        subprocess.Popen(
            ["wireproxy", "--config", str(conf)],
            stdout=open(log, "a"), stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    def stop(self):
        self.running = False


if __name__ == "__main__":
    db.init_db()
    _load_account_proxy()
    w = ProxyWatchdog()
    asyncio.run(w._cycle())
