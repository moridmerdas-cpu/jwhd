import asyncio
import subprocess
import time
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import Config
from models import database as db
from core.warp_pool import (
    POOL_DIR, get_all_configs, get_port_from_conf,
    remove_config, generate_one, find_free_slot, _existing_keys
)


class WarpGuardian:
    def __init__(self, check_interval=120, target=75):
        self.check_interval = check_interval
        self.target = target
        self.running = False

    async def start(self):
        self.running = True
        db.debug_log("warp_health", "start", "OK",
                     f"نگهبان | هر {self.check_interval}s | هدف {self.target}")
        await asyncio.sleep(30)
        while self.running:
            try:
                await self._full_check()
                await self._fill_gaps()
                await self._ensure_running()
            except Exception as e:
                db.debug_log("warp_health", "loop", "ERROR", f"{type(e).__name__}: {e}")
            await asyncio.sleep(self.check_interval)

    async def _full_check(self):
        configs = get_all_configs()
        db.debug_log("warp_health", "check", "START", f"تست {len(configs)}")
        dead = []
        alive = 0
        for i in range(0, len(configs), 10):
            batch = configs[i:i+10]
            tasks = [self._test_port(get_port_from_conf(c)) for c in batch]
            results = await asyncio.gather(*tasks)
            for conf, ok in zip(batch, results):
                if ok:
                    alive += 1
                else:
                    dead.append(conf)
        for conf in dead:
            remove_config(conf)
        db.debug_log("warp_health", "check", "OK", f"سالم {alive} | خراب {len(dead)}")

    async def _fill_gaps(self):
        current = len(get_all_configs())
        needed = self.target - current
        if needed <= 0:
            return
        db.debug_log("warp_health", "fill", "START", f"نیاز {needed}")
        existing = _existing_keys()
        for _ in range(needed):
            slot = find_free_slot()
            if slot == 0:
                break
            ok = await asyncio.get_event_loop().run_in_executor(
                None, generate_one, slot, existing, 10
            )
            if ok:
                self._start_wireproxy(slot)
                await asyncio.sleep(3)
            await asyncio.sleep(8)
        final = len(get_all_configs())
        db.debug_log("warp_health", "fill", "DONE", f"مجموع {final}/{self.target}")

    async def _ensure_running(self):
        started = 0
        for conf in get_all_configs():
            if not self._is_running(conf):
                self._start_wireproxy_by_path(conf)
                started += 1
        if started > 0:
            db.debug_log("warp_health", "ensure", "OK", f"راه‌اندازی {started}")

    async def _test_port(self, port):
        if not port:
            return False
        try:
            proc = await asyncio.create_subprocess_exec(
                "curl", "-s", "--max-time", "10",
                "-x", f"socks5h://127.0.0.1:{port}",
                "https://api.ipify.org",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL
            )
            try:
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=13)
                return proc.returncode == 0 and len(stdout.strip()) > 5
            except asyncio.TimeoutError:
                proc.kill()
                return False
        except Exception:
            return False

    def _is_running(self, conf):
        try:
            r = subprocess.run(["pgrep", "-f", f"wireproxy.*{conf}"],
                               capture_output=True, timeout=3)
            return r.returncode == 0
        except Exception:
            return False

    def _start_wireproxy(self, slot):
        conf = POOL_DIR / f"warp_{slot:03d}.conf"
        self._start_wireproxy_by_path(conf)

    def _start_wireproxy_by_path(self, conf):
        if not conf.exists():
            return
        log = POOL_DIR / f"{conf.stem}.log"
        subprocess.run(["pkill", "-f", f"wireproxy.*{conf}"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.3)
        subprocess.Popen(
            ["wireproxy", "--config", str(conf)],
            stdout=open(log, "a"),
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    def stop(self):
        self.running = False
        db.debug_log("warp_health", "stop", "OK", "متوقف")
