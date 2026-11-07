from aiogram.fsm.state import State, StatesGroup


class AddAccount(StatesGroup):
    waiting_phone    = State()
    waiting_code     = State()
    waiting_password = State()


class SetShiftTiming(StatesGroup):
    waiting_range = State()


class SetGroup(StatesGroup):
    waiting_id = State()
