from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


def main_menu_kb(is_admin: bool = False) -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(text="📊 Мой кабинет")],
        [KeyboardButton(text="➕ Взять дровницу"), KeyboardButton(text="↩️ Вернуть дровницу")],
    ]
    if is_admin:
        buttons.append([KeyboardButton(text="⚙️ Панель администратора")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


def confirm_kb(action: str) -> InlineKeyboardMarkup:
    """Универсальная клавиатура подтверждения."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"confirm:{action}"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="cancel"),
    )
    return builder.as_markup()


def history_pagination_kb(page: int, total_pages: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    buttons = []
    if page > 0:
        buttons.append(InlineKeyboardButton(text="←", callback_data=f"history:page:{page - 1}"))
    buttons.append(InlineKeyboardButton(text=f"{page + 1} / {total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        buttons.append(InlineKeyboardButton(text="→", callback_data=f"history:page:{page + 1}"))
    builder.row(*buttons)
    return builder.as_markup()


def role_selection_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="Замерщик", callback_data="role:measurer"),
        InlineKeyboardButton(text="Менеджер", callback_data="role:manager"),
        InlineKeyboardButton(text="Бригада", callback_data="role:brigade"),
    )
    return builder.as_markup()
