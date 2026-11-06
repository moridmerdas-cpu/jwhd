"""Proxy Loader — خواندن account_proxy.json با cache"""
import json
import time
from pathlib import Path

MAPPING_FILE = Path("/root/tg_master_bot/proxies/account_proxy.json")
_CACHE = {"data": {}, "mtime": 0, "loaded_at": 0}


def get_proxy_for(phone: str):
    try:
        if not MAPPING_FILE.exists():
            return None
        mtime = MAPPING_FILE.stat().st_mtime
        now = time.time()
        if mtime != _CACHE["mtime"] or now - _CACHE["loaded_at"] > 60:
            _CACHE["data"] = json.loads(MAPPING_FILE.read_text())
            _CACHE["mtime"] = mtime
            _CACHE["loaded_at"] = now
    except Exception:
        pass

    entry = _CACHE["data"].get(phone)
    if not entry:
        return None

    if entry.get("source") == "direct" or not entry.get("proxy_type"):
        return None

    return {
        "proxy_type": entry["proxy_type"],
        "addr": entry["addr"],
        "port": int(entry["port"]),
        "rdns": True,
    }
