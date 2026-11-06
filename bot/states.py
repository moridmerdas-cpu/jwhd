from aiogram.dispatcher.filters.state import State, StatesGroup


class AddAccount(StatesGroup):
    waiting_phone = State()
    waiting_code = State()
    waiting_password = State()


class SetChannel(StatesGroup):
    waiting_channel = State()
    waiting_messages = State()
