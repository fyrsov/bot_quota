from aiogram.fsm.state import State, StatesGroup


class AdminReturnStates(StatesGroup):
    waiting_site_number = State()
    confirm = State()


class AdminQuotaStates(StatesGroup):
    choose_target = State()       # роль или конкретный пользователь
    waiting_user_id = State()     # если персональная
    waiting_limit = State()


class AdminDeleteUserStates(StatesGroup):
    confirm = State()


class BroadcastStates(StatesGroup):
    choose_target = State()   # all / specific
    choose_user = State()     # если конкретному — пагинированный выбор
    waiting_text = State()    # текст сообщения
    confirm = State()         # подтверждение перед отправкой
