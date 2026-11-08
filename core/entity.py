"""resolve کردن گروه هدف: یوزرنیم (@name) یا آیدی عددی (-100...)."""
import asyncio


async def resolve_group_entity(client, ref, timeout: float = 15):
    """ref یا یوزرنیم (str) یا آیدی عددی (int) ـه.

    یوزرنیم مستقیم از سرور تلگرام resolve میشه و به کش/عضویت نیاز نداره.
    آیدی عددی با StringSession کش نداره، پس اگه ValueError داد get_dialogs() کش رو پر می‌کنه."""
    if isinstance(ref, str):
        try:
            return await asyncio.wait_for(client.get_entity(ref), timeout=timeout)
        except ValueError:
            raise ValueError(f"یوزرنیم «{ref}» پیدا نشد (گروه عمومی نیست یا اشتباه نوشته شده)")

    try:
        return await asyncio.wait_for(client.get_entity(ref), timeout=timeout)
    except ValueError:
        pass
    for lim in (100, 500, None):
        await asyncio.wait_for(client.get_dialogs(limit=lim), timeout=90)
        try:
            return await asyncio.wait_for(client.get_entity(ref), timeout=timeout)
        except ValueError:
            continue
    raise ValueError(f"اکانت عضو گروه {ref} نیست یا گروه پیدا نشد")
