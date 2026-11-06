"""
چک عضویت همه اکانت‌ها در کانال
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import Config
from models import database as db
from core.engine import make_client


async def check_one(phone, sem):
    async with sem:
        try:
            ss = db.get_session(phone)
            if not ss:
                return phone, "no_session"
            client = make_client(ss, phone=phone)
            await asyncio.wait_for(client.connect(), timeout=30)
            target = Config.TARGET_CHANNEL_USERNAME or Config.TARGET_CHANNEL_ID
            entity = await asyncio.wait_for(client.get_entity(target), timeout=15)

            # چک عضویت
            try:
                from telethon.tl.functions.channels import GetParticipantRequest
                await asyncio.wait_for(
                    client(GetParticipantRequest(channel=entity, participant="me")),
                    timeout=15
                )
                await client.disconnect()
                return phone, "✅ عضو"
            except Exception as e:
                err = str(e).lower()
                await client.disconnect()
                if "not a participant" in err or "user not participant" in err:
                    return phone, "❌ عضو نیست"
                elif "cannot get" in err or "chat admin" in err:
                    return phone, "⚠️  نمی‌تونم چک کنم"
                else:
                    return phone, f"❓ {type(e).__name__}"
        except Exception as e:
            return phone, f"💥 {type(e).__name__}"


async def main():
    db.init_db()
    accounts = db.get_all_accounts()
    print(f"👥 {len(accounts)} اکانت در حال بررسی...\n")

    sem = asyncio.Semaphore(5)
    tasks = [check_one(a["phone"], sem) for a in accounts]
    results = await asyncio.gather(*tasks)

    joined = 0
    not_joined = []
    unknown = []

    for phone, status in results:
        if status == "✅ عضو":
            joined += 1
        elif status == "❌ عضو نیست":
            not_joined.append(phone)
        else:
            unknown.append((phone, status))
        print(f"  {status:20s} | {phone}")

    print()
    print("═" * 50)
    print(f"✅ عضو: {joined}/{len(accounts)}")
    print(f"❌ عضو نیست: {len(not_joined)}")
    print(f"❓ نامشخص: {len(unknown)}")
    print("═" * 50)

    if not_joined:
        print("\nاکانت‌های بدون عضویت:")
        for p in not_joined:
            print(f"  {p}")

    if unknown:
        print("\nنامشخص‌ها:")
        for p, s in unknown:
            print(f"  {p} | {s}")


if __name__ == "__main__":
    asyncio.run(main())
