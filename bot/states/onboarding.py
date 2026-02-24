from aiogram.fsm.state import State, StatesGroup


class OnboardingStates(StatesGroup):
    waiting_full_name = State()
    waiting_phone = State()
    waiting_role = State()
