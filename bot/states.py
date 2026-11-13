from aiogram.fsm.state import State, StatesGroup


class AddAccount(StatesGroup):
    waiting_phone    = State()
    waiting_code     = State()
    waiting_password = State()


class SetShiftTiming(StatesGroup):
    waiting_range = State()


class SetGroup(StatesGroup):
    waiting_id = State()


class UseMembers(StatesGroup):
    waiting_start_bot_link  = State()
    waiting_join_group_link = State()


# ── NEW ──────────────────────────────────────────────────────
class SetNumShifts(StatesGroup):
    waiting_count = State()
