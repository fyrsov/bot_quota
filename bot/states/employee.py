from aiogram.fsm.state import State, StatesGroup


class TakeStates(StatesGroup):
    waiting_site_number = State()
    confirm = State()


class ReturnStates(StatesGroup):
    waiting_site_number = State()
    confirm = State()
