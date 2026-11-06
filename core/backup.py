"""
سیستم بکاپ خودکار
- هر ساعت: دیتابیس + healthy_ports + .env
- ۷ روز نگه‌داری
- فرمت: tar.gz
"""
import asyncio
import subprocess
import shutil
import tarfile
from pathlib import Path
from datetime import datetime, timedelta

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import Config
from models import database as db


BACKUP_DIR = Path("/root/tg_backups")
BACKUP_DIR.mkdir(parents=True, exist_ok=True)
KEEP_DAYS = 7


def create_backup():
    """ساخت یه بکاپ کامل"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = BACKUP_DIR / f"backup_{timestamp}.tar.gz"

    tmp = Path(f"/tmp/backup_{timestamp}")
    tmp.mkdir(parents=True, exist_ok=True)

    try:
        # دیتابیس (اگه WAL داره، checkpoint کن)
        try:
            conn = db.get_conn()
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            conn.close()
        except Exception:
            pass

        # کپی دیتابیس
        if Config.DB_PATH.exists():
            shutil.copy2(Config.DB_PATH, tmp / "tg_system.db")

        # .env
        env_file = Config.BASE_DIR / ".env"
        if env_file.exists():
            shutil.copy2(env_file, tmp / ".env")

        # healthy_ports
        hp = Config.BASE_DIR / "proxies" / "healthy_ports.json"
        if hp.exists():
            shutil.copy2(hp, tmp / "healthy_ports.json")

        # warp_pool configs
        pool = Config.PROXY_DIR / "warp_pool"
        if pool.exists():
            dst_pool = tmp / "warp_pool"
            dst_pool.mkdir()
            for f in pool.glob("warp_*.conf"):
                shutil.copy2(f, dst_pool / f.name)

        # tar.gz
        with tarfile.open(backup_file, "w:gz") as tar:
            tar.add(tmp, arcname=f"backup_{timestamp}")

        db.debug_log("backup", "create", "OK",
                     f"{backup_file.name} ({backup_file.stat().st_size // 1024}KB)")
        return backup_file
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def cleanup_old():
    """حذف بکاپ‌های قدیمی‌تر از KEEP_DAYS روز"""
    cutoff = datetime.now() - timedelta(days=KEEP_DAYS)
    removed = 0
    for f in BACKUP_DIR.glob("backup_*.tar.gz"):
        try:
            mtime = datetime.fromtimestamp(f.stat().st_mtime)
            if mtime < cutoff:
                f.unlink()
                removed += 1
        except Exception:
            pass
    if removed:
        db.debug_log("backup", "cleanup", "OK", f"{removed} بکاپ قدیمی حذف شد")


async def backup_loop(interval_hours=1):
    """حلقه بکاپ هر N ساعت"""
    await asyncio.sleep(60)  # ۱ دقیقه صبر اول
    while True:
        try:
            create_backup()
            cleanup_old()
        except Exception as e:
            db.debug_log("backup", "loop", "ERROR", f"{type(e).__name__}: {e}")
        await asyncio.sleep(interval_hours * 3600)


if __name__ == "__main__":
    create_backup()
    cleanup_old()
    print(f"✅ بکاپ‌ها در: {BACKUP_DIR}")
    for f in sorted(BACKUP_DIR.glob("*.tar.gz"))[-5:]:
        size_kb = f.stat().st_size // 1024
        print(f"   {f.name} ({size_kb}KB)")
