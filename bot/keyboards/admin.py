from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.database.models import ROLE_LABELS, ROLES


def admin_menu_kb() -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(text="👥 Сотрудники"), KeyboardButton(text="📊 Статистика")],
        [KeyboardButton(text="🔧 Квоты"), KeyboardButton(text="↩️ Вернуть (админ)")],
        [KeyboardButton(text="📥 Выгрузить отчёт"), KeyboardButton(text="📢 Рассылка")],
        [KeyboardButton(text="◀️ Назад")],
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


def broadcast_target_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="👥 Всем сотрудникам", callback_data="broadcast:all"),
    )
    builder.row(
        InlineKeyboardButton(text="👤 Конкретному сотруднику", callback_data="broadcast:one"),
    )
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="cancel"))
    return builder.as_markup()


def quota_target_kb() -> InlineKeyboardMarkup:
    """Выбор: изменить квоту по роли или персональную."""
    builder = InlineKeyboardBuilder()
    for role in ROLES:
        builder.row(
            InlineKeyboardButton(
                text=f"Роль: {ROLE_LABELS[role]}",
                callback_data=f"quota_role:{role}",
            )
        )
    builder.row(
        InlineKeyboardButton(text="Персональная (по ID)", callback_data="quota_personal")
    )
    builder.row(
        InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")
    )
    return builder.as_markup()


def stats_period_kb(has_months: bool, prefix: str = "stats_period") -> InlineKeyboardMarkup:
    """Выбор периода для статистики или экспорта."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📅 Текущий месяц", callback_data=f"{prefix}:1"),
        InlineKeyboardButton(text="📅 3 месяца",      callback_data=f"{prefix}:3"),
    )
    builder.row(
        InlineKeyboardButton(text="📅 6 месяцев",     callback_data=f"{prefix}:6"),
        InlineKeyboardButton(text="📅 Весь период",   callback_data=f"{prefix}:0"),
    )
    if has_months:
        builder.row(
            InlineKeyboardButton(text="🗓 Конкретный месяц", callback_data=f"{prefix}:pick")
        )
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="cancel"))
    return builder.as_markup()


def months_kb(months: list[str], prefix: str = "month") -> InlineKeyboardMarkup:
    """Список месяцев для статистики / отчёта. prefix разделяет назначение."""
    builder = InlineKeyboardBuilder()
    from datetime import datetime
    for month in months:
        label = datetime.strptime(month, "%Y-%m").strftime("%B %Y")
        builder.row(InlineKeyboardButton(text=label, callback_data=f"{prefix}:{month}"))
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="cancel"))
    return builder.as_markup()


def users_list_kb(
    users: list, page: int, total_pages: int, action: str
) -> InlineKeyboardMarkup:
    """Пагинированный список сотрудников."""
    builder = InlineKeyboardBuilder()
    for user in users:
        builder.row(
            InlineKeyboardButton(
                text=f"{user.full_name} ({ROLE_LABELS.get(user.role, user.role)})",
                callback_data=f"{action}:user:{user.telegram_id}",
            )
        )
    nav_buttons = []
    if page > 0:
        nav_buttons.append(
            InlineKeyboardButton(text="←", callback_data=f"{action}:page:{page - 1}")
        )
    nav_buttons.append(
        InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop")
    )
    if page < total_pages - 1:
        nav_buttons.append(
            InlineKeyboardButton(text="→", callback_data=f"{action}:page:{page + 1}")
        )
    if nav_buttons:
        builder.row(*nav_buttons)
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="cancel"))
    return builder.as_markup()


def confirm_kb(action: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"confirm:{action}"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="cancel"),
    )
    return builder.as_markup()
