from aiogram.fsm.state import State, StatesGroup


class AddAccount(StatesGroup):
    waiting_phone    = State()
    waiting_code     = State()
    waiting_password = State()


class SetChannel(StatesGroup):
    waiting_channel  = State()
    waiting_messages = State()


class ShiftSchedule(StatesGroup):
    waiting_range = State()   # منتظر ورودی "HH-HH" برای یک شیفت مشخص
