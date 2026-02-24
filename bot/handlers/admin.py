import asyncio
import logging
import re
from collections import defaultdict
from datetime import datetime

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Filter
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import ROLE_LABELS, ROLES, User
from bot.database.repositories.quota_repo import QuotaRepo
from bot.database.repositories.record_repo import RecordRepo
from bot.database.repositories.user_repo import UserRepo
from bot.keyboards.admin import (
    admin_menu_kb,
    broadcast_target_kb,
    confirm_kb,
    months_kb,
    quota_target_kb,
    stats_period_kb,
    users_list_kb,
)
from bot.keyboards.employee import main_menu_kb
from bot.services.export_service import build_excel
from bot.services.quota_service import QuotaService
from bot.states.admin import AdminDeleteUserStates, AdminQuotaStates, AdminReturnStates, BroadcastStates

logger = logging.getLogger(__name__)

router = Router(name="admin")

_SITE_RE = re.compile(r"^[\w\-/\.]{1,100}$")
_USERS_PAGE_SIZE = 8


class IsAdmin(Filter):
    async def __call__(self, event, is_admin: bool = False) -> bool:
        return is_admin


router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


# ---------------------------------------------------------------------------
# Панель администратора
# ---------------------------------------------------------------------------

@router.message(F.text == "⚙️ Панель администратора")
async def admin_panel(message: Message) -> None:
    await message.answer("Панель администратора:", reply_markup=admin_menu_kb())


@router.message(F.text == "◀️ Назад")
async def admin_back(message: Message, is_admin: bool, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Главное меню:", reply_markup=main_menu_kb(is_admin))


# ---------------------------------------------------------------------------
# Список сотрудников
# ---------------------------------------------------------------------------

@router.message(F.text == "👥 Сотрудники")
async def employees_list(message: Message, session: AsyncSession) -> None:
    repo = UserRepo(session)
    users = await repo.get_all()
    if not users:
        await message.answer("Нет зарегистрированных сотрудников.")
        return

    total_pages = max(1, (len(users) + _USERS_PAGE_SIZE - 1) // _USERS_PAGE_SIZE)
    page_users = users[:_USERS_PAGE_SIZE]
    await message.answer(
        f"Зарегистрировано сотрудников: <b>{len(users)}</b>",
        parse_mode="HTML",
        reply_markup=users_list_kb(page_users, 0, total_pages, "emp"),
    )


@router.callback_query(F.data.startswith("emp:page:"))
async def employees_page(callback: CallbackQuery, session: AsyncSession) -> None:
    try:
        page = int(callback.data.split(":")[-1])
    except ValueError:
        await callback.answer("Некорректный запрос", show_alert=True)
        return
    repo = UserRepo(session)
    users = await repo.get_all()
    total_pages = max(1, (len(users) + _USERS_PAGE_SIZE - 1) // _USERS_PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    page_users = users[page * _USERS_PAGE_SIZE: (page + 1) * _USERS_PAGE_SIZE]
    await callback.message.edit_reply_markup(
        reply_markup=users_list_kb(page_users, page, total_pages, "emp")
    )
    await callback.answer()


@router.callback_query(F.data.startswith("emp:user:"))
async def employee_detail(
    callback: CallbackQuery, session: AsyncSession, state: FSMContext
) -> None:
    try:
        user_id = int(callback.data.split(":")[-1])
    except ValueError:
        await callback.answer("Некорректный запрос", show_alert=True)
        return
    repo = UserRepo(session)
    quota_repo = QuotaRepo(session)
    record_repo = RecordRepo(session)

    user = await repo.get_by_telegram_id(user_id)
    if not user:
        await callback.answer("Пользователь не найден", show_alert=True)
        return

    limit = await quota_repo.get_limit(user.telegram_id, user.role)
    used = await record_repo.count_used(user.telegram_id)

    personal = await quota_repo.get_personal(user.telegram_id)
    quota_info = (
        f"Персональная: {personal.monthly_limit}"
        if personal
        else f"По роли: {limit}"
    )

    text = (
        f"👤 <b>{user.full_name}</b>\n"
        f"💼 {ROLE_LABELS.get(user.role, user.role)}\n"
        f"📱 {user.phone}\n"
        f"🆔 {user.telegram_id}\n"
        f"📦 Квота: {quota_info} | Использовано: {used}/{limit}\n"
        f"🛡 Админ: {'да' if user.is_admin else 'нет'}\n"
        f"📅 Регистрация: {user.created_at.strftime('%d.%m.%Y') if user.created_at else '?'}"
    )

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="🗑 Удалить сотрудника",
            callback_data=f"del_user:{user_id}",
        )
    )
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="emp:back"))

    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data == "emp:back")
async def employees_back(callback: CallbackQuery, session: AsyncSession) -> None:
    repo = UserRepo(session)
    users = await repo.get_all()
    total_pages = max(1, (len(users) + _USERS_PAGE_SIZE - 1) // _USERS_PAGE_SIZE)
    page_users = users[:_USERS_PAGE_SIZE]
    await callback.message.edit_text(
        f"Зарегистрировано сотрудников: <b>{len(users)}</b>",
        parse_mode="HTML",
        reply_markup=users_list_kb(page_users, 0, total_pages, "emp"),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Удаление сотрудника
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("del_user:"))
async def delete_user_confirm(
    callback: CallbackQuery, session: AsyncSession, state: FSMContext
) -> None:
    try:
        user_id = int(callback.data.split(":")[-1])
    except ValueError:
        await callback.answer("Некорректный запрос", show_alert=True)
        return

    # Нельзя удалить самого себя
    if user_id == callback.from_user.id:
        await callback.answer("Нельзя удалить собственную учётную запись.", show_alert=True)
        return

    repo = UserRepo(session)
    user = await repo.get_by_telegram_id(user_id)
    if not user:
        await callback.answer("Пользователь не найден", show_alert=True)
        return

    await state.update_data(del_user_id=user_id)
    await callback.message.edit_text(
        f"Удалить сотрудника <b>{user.full_name}</b>?\n"
        "Все его записи также будут удалены.",
        parse_mode="HTML",
        reply_markup=confirm_kb("del_user"),
    )
    await state.set_state(AdminDeleteUserStates.confirm)
    await callback.answer()


@router.callback_query(AdminDeleteUserStates.confirm, F.data == "confirm:del_user")
async def delete_user_execute(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    data = await state.get_data()
    user_id = data.get("del_user_id")
    await state.clear()

    repo = UserRepo(session)
    deleted = await repo.delete(user_id)
    if deleted:
        await callback.message.edit_text("✅ Сотрудник удалён.")
    else:
        await callback.message.edit_text("Пользователь не найден.")
    await callback.answer()


# ---------------------------------------------------------------------------
# Статистика
# ---------------------------------------------------------------------------

def _last_n_months(n: int) -> list[str]:
    """Возвращает список из n последних месяцев включая текущий."""
    from dateutil.relativedelta import relativedelta  # type: ignore[import-untyped]
    now = datetime.now()
    return [(now - relativedelta(months=i)).strftime("%Y-%m") for i in range(n)]


def _build_stats_text(records: list, user_map: dict, months: list[str], period_label: str) -> str:
    if not records:
        return f"📊 <b>{period_label}</b>\n\nДанных за этот период нет."

    # Группируем по сотруднику, внутри — по месяцу
    by_user: dict[int, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for rec in records:
        by_user[rec.user_id][rec.month].append(rec)

    # Сортируем месяцы от новых к старым для заголовков колонок
    sorted_months = sorted(months, reverse=True)
    month_short = {m: datetime.strptime(m, "%Y-%m").strftime("%b'%y") for m in sorted_months}

    lines = [f"📊 <b>{period_label}</b>", f"Всего выдано: <b>{len(records)}</b>\n"]
    for uid, months_data in sorted(by_user.items(), key=lambda x: -sum(len(v) for v in x[1].values())):
        u = user_map.get(uid)
        name = u.full_name if u else f"ID:{uid}"
        role = ROLE_LABELS.get(u.role, u.role) if u else "—"
        total = sum(len(v) for v in months_data.values())
        lines.append(f"👤 <b>{name}</b> ({role}) — {total} шт.")

        # Разбивка по месяцам в одну строку: Фев'26: 3 | Янв'26: 4
        month_parts = [
            f"{month_short[m]}: {len(months_data[m])}"
            for m in sorted_months
            if m in months_data
        ]
        if len(sorted_months) > 1:
            lines.append("  " + " | ".join(month_parts))
        lines.append("")

    return "\n".join(lines).strip()


@router.message(F.text == "📊 Статистика")
async def stats_choose_period(message: Message, session: AsyncSession) -> None:
    record_repo = RecordRepo(session)
    months = await record_repo.get_stats_months()
    if not months:
        await message.answer("Нет данных для статистики.")
        return
    await message.answer("Выберите период:", reply_markup=stats_period_kb(has_months=True))


@router.callback_query(F.data.startswith("stats_period:"))
async def stats_period(callback: CallbackQuery, session: AsyncSession) -> None:
    value = callback.data.split(":", 1)[1]

    if value == "pick":
        record_repo = RecordRepo(session)
        months = await record_repo.get_stats_months()
        await callback.message.edit_text(
            "Выберите месяц:", reply_markup=months_kb(months, prefix="month")
        )
        await callback.answer()
        return

    record_repo = RecordRepo(session)
    user_repo = UserRepo(session)
    all_months = await record_repo.get_stats_months()

    try:
        n = int(value)
    except ValueError:
        await callback.answer("Некорректный запрос", show_alert=True)
        return
    if n == 0:
        target_months = all_months  # весь период
        period_label = "Статистика за весь период"
    else:
        target_months = [m for m in _last_n_months(n) if m in all_months]
        labels = {1: "текущий месяц", 3: "3 месяца", 6: "6 месяцев"}
        period_label = f"Статистика за {labels.get(n, f'{n} мес.')}"

    if not target_months:
        await callback.message.edit_text("Нет данных за выбранный период.")
        await callback.answer()
        return

    records = await record_repo.get_by_months(target_months)
    users = await user_repo.get_all()
    user_map = {u.telegram_id: u for u in users}

    text = _build_stats_text(records, user_map, target_months, period_label)
    await callback.message.edit_text(text, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("month:"))
async def stats_single_month(callback: CallbackQuery, session: AsyncSession) -> None:
    month = callback.data.split(":", 1)[1]
    if not re.match(r"^\d{4}-\d{2}$", month):
        await callback.answer("Некорректный формат месяца", show_alert=True)
        return

    record_repo = RecordRepo(session)
    user_repo = UserRepo(session)
    records = await record_repo.get_by_months([month])
    users = await user_repo.get_all()
    user_map = {u.telegram_id: u for u in users}

    dt = datetime.strptime(month, "%Y-%m")
    period_label = f"Статистика за {dt.strftime('%B %Y').capitalize()}"
    text = _build_stats_text(records, user_map, [month], period_label)
    await callback.message.edit_text(text, parse_mode="HTML")
    await callback.answer()


# ---------------------------------------------------------------------------
# Управление квотами
# ---------------------------------------------------------------------------

@router.message(F.text == "🔧 Квоты")
async def quotas_menu(message: Message, state: FSMContext) -> None:
    await message.answer("Выберите, для кого изменить квоту:", reply_markup=quota_target_kb())
    await state.set_state(AdminQuotaStates.choose_target)


@router.callback_query(AdminQuotaStates.choose_target, F.data.startswith("quota_role:"))
async def quota_role_selected(callback: CallbackQuery, state: FSMContext) -> None:
    role = callback.data.split(":")[-1]
    if role not in ROLES:
        await callback.answer("Неверная роль", show_alert=True)
        return
    await state.update_data(quota_target="role", quota_role=role)
    await callback.message.edit_text(
        f"Введите новый лимит для роли <b>{ROLE_LABELS[role]}</b> (целое число):",
        parse_mode="HTML",
    )
    await state.set_state(AdminQuotaStates.waiting_limit)
    await callback.answer()


@router.callback_query(AdminQuotaStates.choose_target, F.data == "quota_personal")
async def quota_personal_selected(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(quota_target="personal")
    await callback.message.edit_text("Введите <b>Telegram ID</b> сотрудника:", parse_mode="HTML")
    await state.set_state(AdminQuotaStates.waiting_user_id)
    await callback.answer()


@router.message(AdminQuotaStates.waiting_user_id)
async def quota_personal_user_id(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    text = (message.text or "").strip()
    if not text.lstrip("-").isdigit():
        await message.answer("Введите числовой Telegram ID:")
        return
    user_id = int(text)
    repo = UserRepo(session)
    user = await repo.get_by_telegram_id(user_id)
    if not user:
        await message.answer("Сотрудник с таким ID не найден. Попробуйте ещё раз:")
        return
    await state.update_data(quota_user_id=user_id)
    await message.answer(
        f"Введите новый лимит для <b>{user.full_name}</b> (целое число):",
        parse_mode="HTML",
    )
    await state.set_state(AdminQuotaStates.waiting_limit)


@router.message(AdminQuotaStates.waiting_limit)
async def quota_set_limit(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    text = (message.text or "").strip()
    if not text.isdigit() or len(text) > 5 or int(text) < 0 or int(text) > 1000:
        await message.answer("Введите целое число от 0 до 1000:")
        return

    limit = int(text)
    data = await state.get_data()
    await state.clear()

    quota_repo = QuotaRepo(session)

    quota_target = data.get("quota_target")
    if not quota_target:
        await message.answer("Ошибка сессии. Начните заново через 🔧 Квоты.")
        return

    if quota_target == "role":
        role = data.get("quota_role")
        if not role or role not in ROLES:
            await message.answer("Ошибка: роль не определена. Начните заново.")
            return
        await quota_repo.set_role_limit(role, limit)
        await message.answer(
            f"✅ Квота для роли <b>{ROLE_LABELS[role]}</b> установлена: {limit}",
            parse_mode="HTML",
        )
    else:
        user_id = data.get("quota_user_id")
        if not user_id:
            await message.answer("Ошибка: сотрудник не выбран. Начните заново.")
            return
        repo = UserRepo(session)
        user = await repo.get_by_telegram_id(user_id)
        await quota_repo.set_personal_limit(user_id, limit)
        name = user.full_name if user else str(user_id)
        await message.answer(
            f"✅ Персональная квота для <b>{name}</b> установлена: {limit}",
            parse_mode="HTML",
        )


# ---------------------------------------------------------------------------
# Возврат дровницы администратором
# ---------------------------------------------------------------------------

@router.message(F.text == "↩️ Вернуть (админ)")
async def admin_return_start(message: Message, state: FSMContext) -> None:
    await message.answer(
        "Введите <b>номер договора / стройки</b> для возврата:",
        parse_mode="HTML",
    )
    await state.set_state(AdminReturnStates.waiting_site_number)


@router.message(AdminReturnStates.waiting_site_number)
async def admin_return_site(message: Message, state: FSMContext, session: AsyncSession) -> None:
    text = (message.text or "").strip()
    if not text or len(text) > 100:
        await message.answer("Введите номер договора (не более 100 символов):")
        return
    if not _SITE_RE.match(text):
        await message.answer(
            "Номер договора может содержать только буквы, цифры, дефис, точку и /.\n"
            "Попробуйте ещё раз:"
        )
        return

    # Проверяем существование до подтверждения
    record_repo = RecordRepo(session)
    user_repo = UserRepo(session)
    record = await record_repo.find_active_any_user(text)
    if not record:
        await message.answer(
            f"Запись с договором <b>№{text}</b> за текущий месяц не найдена.",
            parse_mode="HTML",
        )
        await state.clear()
        return

    user = await user_repo.get_by_telegram_id(record.user_id)
    user_name = user.full_name if user else f"ID:{record.user_id}"
    date_str = record.created_at.strftime("%d.%m.%Y %H:%M") if record.created_at else "?"

    await state.update_data(site_number=text)
    await message.answer(
        f"Найдена запись:\n\n"
        f"👤 Сотрудник: <b>{user_name}</b>\n"
        f"📋 №{record.site_number}\n"
        f"📅 {date_str}\n\n"
        "Подтвердить возврат?",
        parse_mode="HTML",
        reply_markup=confirm_kb("admin_return"),
    )
    await state.set_state(AdminReturnStates.confirm)


@router.callback_query(AdminReturnStates.confirm, F.data == "confirm:admin_return")
async def admin_return_confirm(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    data = await state.get_data()
    site_number = data.get("site_number", "")
    await state.clear()

    service = QuotaService(session)
    record = await service.return_admin(site_number)

    if record is None:
        await callback.message.edit_text(
            f"Запись с договором <b>№{site_number}</b> уже отменена или не найдена.",
            parse_mode="HTML",
        )
    else:
        await callback.message.edit_text(
            f"✅ Дровница по договору <b>№{site_number}</b> возвращена.",
            parse_mode="HTML",
        )
    await callback.answer()


# ---------------------------------------------------------------------------
# Выгрузить Excel-отчёт
# ---------------------------------------------------------------------------

@router.message(F.text == "📥 Выгрузить отчёт")
async def export_choose_period(message: Message, session: AsyncSession) -> None:
    record_repo = RecordRepo(session)
    months = await record_repo.get_stats_months()
    if not months:
        await message.answer("Нет данных для выгрузки.")
        return
    await message.answer("Выберите период для выгрузки:", reply_markup=stats_period_kb(has_months=True, prefix="export_period"))


@router.callback_query(F.data.startswith("export_period:"))
async def export_period(callback: CallbackQuery, session: AsyncSession) -> None:
    value = callback.data.split(":", 1)[1]

    if value == "pick":
        record_repo = RecordRepo(session)
        months = await record_repo.get_stats_months()
        await callback.message.edit_text(
            "Выберите месяц:", reply_markup=months_kb(months, prefix="export_month")
        )
        await callback.answer()
        return

    record_repo = RecordRepo(session)
    all_months = await record_repo.get_stats_months()

    try:
        n = int(value)
    except ValueError:
        await callback.answer("Некорректный запрос", show_alert=True)
        return
    if n == 0:
        target_months = all_months
        caption_label = "весь период"
        filename = "report_all.xlsx"
    else:
        target_months = [m for m in _last_n_months(n) if m in all_months]
        labels = {1: "текущий месяц", 3: "3 месяца", 6: "6 месяцев"}
        caption_label = labels.get(n, f"{n} мес.")
        filename = f"report_last{n}m.xlsx"

    if not target_months:
        await callback.message.edit_text("Нет данных за выбранный период.")
        await callback.answer()
        return

    await callback.answer("Генерирую отчёт...")
    excel_bytes = await build_excel(session, target_months)
    await callback.message.answer_document(
        BufferedInputFile(excel_bytes, filename=filename),
        caption=f"📥 Отчёт за {caption_label}",
    )


@router.callback_query(F.data.startswith("export_month:"))
async def export_single_month(callback: CallbackQuery, session: AsyncSession) -> None:
    month = callback.data.split(":", 1)[1]
    if not re.match(r"^\d{4}-\d{2}$", month):
        await callback.answer("Некорректный формат", show_alert=True)
        return

    await callback.answer("Генерирую отчёт...")
    excel_bytes = await build_excel(session, [month])

    dt = datetime.strptime(month, "%Y-%m")
    await callback.message.answer_document(
        BufferedInputFile(excel_bytes, filename=f"report_{month}.xlsx"),
        caption=f"📥 Отчёт за {dt.strftime('%B %Y')}",
    )


# ---------------------------------------------------------------------------
# Рассылка
# ---------------------------------------------------------------------------

_MAX_BROADCAST_LEN = 3000


@router.message(F.text == "📢 Рассылка")
async def broadcast_start(message: Message, state: FSMContext) -> None:
    await message.answer("Кому отправить сообщение?", reply_markup=broadcast_target_kb())
    await state.set_state(BroadcastStates.choose_target)


@router.callback_query(BroadcastStates.choose_target, F.data == "broadcast:all")
async def broadcast_choose_all(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(broadcast_target="all", broadcast_user_id=None)
    await callback.message.edit_text("Введите текст сообщения для всех сотрудников:")
    await state.set_state(BroadcastStates.waiting_text)
    await callback.answer()


@router.callback_query(BroadcastStates.choose_target, F.data == "broadcast:one")
async def broadcast_choose_one(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    repo = UserRepo(session)
    users = await repo.get_all()
    if not users:
        await callback.message.edit_text("Нет зарегистрированных сотрудников.")
        await state.clear()
        await callback.answer()
        return
    total_pages = max(1, (len(users) + _USERS_PAGE_SIZE - 1) // _USERS_PAGE_SIZE)
    await callback.message.edit_text(
        "Выберите сотрудника:",
        reply_markup=users_list_kb(users[:_USERS_PAGE_SIZE], 0, total_pages, "bcast"),
    )
    await state.set_state(BroadcastStates.choose_user)
    await callback.answer()


@router.callback_query(BroadcastStates.choose_user, F.data.startswith("bcast:page:"))
async def broadcast_user_page(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    page = int(callback.data.split(":")[-1])
    repo = UserRepo(session)
    users = await repo.get_all()
    total_pages = max(1, (len(users) + _USERS_PAGE_SIZE - 1) // _USERS_PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    page_users = users[page * _USERS_PAGE_SIZE: (page + 1) * _USERS_PAGE_SIZE]
    await callback.message.edit_reply_markup(
        reply_markup=users_list_kb(page_users, page, total_pages, "bcast")
    )
    await callback.answer()


@router.callback_query(BroadcastStates.choose_user, F.data.startswith("bcast:user:"))
async def broadcast_user_selected(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    user_id = int(callback.data.split(":")[-1])
    repo = UserRepo(session)
    user = await repo.get_by_telegram_id(user_id)
    if not user:
        await callback.answer("Пользователь не найден", show_alert=True)
        return
    await state.update_data(broadcast_target="one", broadcast_user_id=user_id)
    await callback.message.edit_text(
        f"Введите текст сообщения для <b>{user.full_name}</b>:",
        parse_mode="HTML",
    )
    await state.set_state(BroadcastStates.waiting_text)
    await callback.answer()


@router.message(BroadcastStates.waiting_text)
async def broadcast_got_text(message: Message, state: FSMContext, session: AsyncSession) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer("Сообщение не может быть пустым. Введите текст:")
        return
    if len(text) > _MAX_BROADCAST_LEN:
        await message.answer(f"Слишком длинное сообщение (макс. {_MAX_BROADCAST_LEN} символов). Попробуйте ещё раз:")
        return

    await state.update_data(broadcast_text=text)
    data = await state.get_data()

    if data["broadcast_target"] == "all":
        repo = UserRepo(session)
        users = await repo.get_all()
        preview = f"Отправить всем сотрудникам (<b>{len(users)}</b> чел.):\n\n"
    else:
        repo = UserRepo(session)
        user = await repo.get_by_telegram_id(data["broadcast_user_id"])
        name = user.full_name if user else str(data["broadcast_user_id"])
        preview = f"Отправить сотруднику <b>{name}</b>:\n\n"

    await message.answer(
        f"{preview}"
        f"<blockquote>{text}</blockquote>",
        parse_mode="HTML",
        reply_markup=confirm_kb("broadcast"),
    )
    await state.set_state(BroadcastStates.confirm)


@router.callback_query(BroadcastStates.confirm, F.data == "confirm:broadcast")
async def broadcast_send(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession, bot: Bot
) -> None:
    data = await state.get_data()
    await state.clear()

    text = f"📢 <b>Сообщение от администратора:</b>\n\n{data['broadcast_text']}"
    repo = UserRepo(session)

    if data["broadcast_target"] == "all":
        users = await repo.get_all()
    else:
        u = await repo.get_by_telegram_id(data["broadcast_user_id"])
        users = [u] if u else []

    sent, failed = 0, 0
    for user in users:
        try:
            await bot.send_message(user.telegram_id, text, parse_mode="HTML")
            sent += 1
            await asyncio.sleep(0.05)  # ~20 msg/sec — в пределах лимитов Telegram
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)
            try:
                await bot.send_message(user.telegram_id, text, parse_mode="HTML")
                sent += 1
            except Exception as retry_err:
                failed += 1
                logger.warning("Broadcast retry failed for user %s: %s", user.telegram_id, retry_err)
        except (TelegramForbiddenError, TelegramBadRequest) as e:
            failed += 1
            logger.warning("Broadcast failed for user %s: %s", user.telegram_id, e)

    result = f"✅ Отправлено: <b>{sent}</b>"
    if failed:
        result += f"\n⚠️ Не доставлено (заблокировали бота): <b>{failed}</b>"

    await callback.message.edit_text(result, parse_mode="HTML")
    await callback.answer()


# ---------------------------------------------------------------------------
# Отмена FSM (admin)
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "cancel")
async def admin_cancel(callback: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    await state.clear()
    await callback.message.edit_text("Действие отменено.")
    await callback.message.answer("Панель администратора:", reply_markup=admin_menu_kb())
    await callback.answer()
