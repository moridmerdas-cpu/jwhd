"""Engine — Telethon Client maker + instant_view"""
import asyncio
import sys
from pathlib import Path
from datetime import datetime, timedelta

from telethon import TelegramClient, functions
from telethon.sessions import StringSession
from telethon.errors import (
    FloodWaitError, AuthKeyError, SessionRevokedError,
    UserDeactivatedBanError,
)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import Config
from models import database as db


def make_client(session_string, proxy=None, phone=None):
    """ساخت کلاینت با proxy per-phone"""
    client = TelegramClient(
        StringSession(session_string),
        Config.API_ID,
        Config.API_HASH,
        connection_retries=3,
        retry_delay=1,
        timeout=20,
        request_retries=3,
    )

    if proxy:
        client.set_proxy(proxy)
        return client

    if phone:
        try:
            from core.proxy_loader import get_proxy_for
            p = get_proxy_for(phone)
            if p:
                client.set_proxy(p)
        except Exception:
            pass

    return client


async def instant_view(client, channel, message_ids):
    try:
        r = await client(functions.messages.GetMessagesViewsRequest(
            peer=channel, id=message_ids, increment=True))
        return {"ok": True, "result": r}
    except FloodWaitError as e:
        return {"ok": False, "flood": e.seconds, "error": f"FloodWait {e.seconds}s"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def health_check(client):
    try:
        me = await client.get_me()
        return {"status": "ok", "user": me.username or me.first_name}
    except FloodWaitError as e:
        return {"status": "flood", "seconds": e.seconds}
    except (AuthKeyError, SessionRevokedError):
        return {"status": "dead"}
    except UserDeactivatedBanError:
        return {"status": "banned"}
    except Exception as e:
        return {"status": "error", "error": str(e)}
