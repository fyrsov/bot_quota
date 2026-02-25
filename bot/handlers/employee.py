import re
from collections import defaultdict
from datetime import datetime

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import ROLE_LABELS, User
from bot.database.repositories.record_repo import RecordRepo
from bot.keyboards.employee import (
    confirm_kb,
    history_pagination_kb,
    main_menu_kb,
)
from bot.config import fmt_dt
from bot.services.quota_service import QuotaService
from bot.states.employee import ReturnStates, TakeStates

router = Router(name="employee")

_SITE_RE = re.compile(r"^[\w\-/\.]{1,100}$")
_HISTORY_PAGE_SIZE = 15  # записей на страницу (для группировки ~3 месяца)


def _require_user(user: User | None) -> bool:
    return user is not None


# ---------------------------------------------------------------------------
# Главное меню / кабинет
# ---------------------------------------------------------------------------

@router.message(F.text == "📊 Мой кабинет")
async def cabinet(message: Message, user: User | None, is_admin: bool, session: AsyncSession) -> None:
    if not _require_user(user):
        await message.answer("Сначала зарегистрируйтесь. Отправьте /start")
        return

    service = QuotaService(session)
    status = await service.get_status(user)

    record_repo = RecordRepo(session)
    total = await record_repo.count_history(user.telegram_id)

    text = (
        f"👤 <b>{user.full_name}</b>\n"
        f"💼 {ROLE_LABELS.get(user.role, user.role)}\n\n"
        f"📦 Квота на этот месяц: <b>{status.remaining} из {status.limit}</b> (использовано: {status.used})\n\n"
        f"Всего записей: {total}"
    )
    await message.answer(text, parse_mode="HTML")

    # Передаём уже посчитанный total, чтобы не делать второй запрос
    await _send_history_page(message, user, session, page=0, edit=False, total=total)


async def _send_history_page(
    message: Message,
    user: User,
    session: AsyncSession,
    page: int,
    edit: bool = False,
    total: int | None = None,
) -> None:
    record_repo = RecordRepo(session)
    if total is None:
        total = await record_repo.count_history(user.telegram_id)
    total_pages = max(1, (total + _HISTORY_PAGE_SIZE - 1) // _HISTORY_PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))

    records = await record_repo.get_history(
        user.telegram_id,
        offset=page * _HISTORY_PAGE_SIZE,
        limit=_HISTORY_PAGE_SIZE,
    )

    if not records:
        await message.answer("История пуста.")
        return

    # Группируем по месяцу
    grouped: dict[str, list] = defaultdict(list)
    for rec in records:
        grouped[rec.month].append(rec)

    lines = ["<b>📋 История дровниц</b>\n"]
    for month_key in sorted(grouped.keys(), reverse=True):
        month_records = grouped[month_key]
        dt = datetime.strptime(month_key, "%Y-%m")
        month_label = dt.strftime("%B %Y").capitalize()
        lines.append(f"▸ <b>{month_label}</b> — взято: {len(month_records)}")
        for rec in month_records:
            date_str = rec.created_at.strftime("%d.%m") if rec.created_at else "?"
            lines.append(f"  · №{rec.site_number} от {date_str}")
        lines.append("")

    text = "\n".join(lines).strip()
    kb = history_pagination_kb(page, total_pages) if total_pages > 1 else None

    if edit:
        await message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    else:
        await message.answer(text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data.startswith("history:page:"))
async def history_page_callback(
    callback: CallbackQuery, user: User | None, session: AsyncSession
) -> None:
    if not _require_user(user):
        await callback.answer("Не зарегистрированы", show_alert=True)
        return
    try:
        page = int(callback.data.split(":")[-1])
    except ValueError:
        await callback.answer("Некорректный запрос", show_alert=True)
        return
    await _send_history_page(callback.message, user, session, page=page, edit=True)
    await callback.answer()


# ---------------------------------------------------------------------------
# Взять дровницу
# ---------------------------------------------------------------------------

@router.message(F.text == "➕ Взять дровницу")
async def take_start(message: Message, user: User | None, session: AsyncSession, state: FSMContext) -> None:
    if not _require_user(user):
        await message.answer("Сначала зарегистрируйтесь. Отправьте /start")
        return

    service = QuotaService(session)
    status = await service.get_status(user)
    if not status.has_quota:
        await message.answer(
            f"Квота на этот месяц исчерпана (использовано {status.used} из {status.limit}).\n"
            "Обратитесь к администратору."
        )
        return

    await message.answer(
        f"Осталось квоты: <b>{status.remaining} из {status.limit}</b>\n\n"
        "Введите <b>номер договора / стройки</b>:",
        parse_mode="HTML",
    )
    await state.set_state(TakeStates.waiting_site_number)


@router.message(TakeStates.waiting_site_number)
async def take_site_number(
    message: Message, state: FSMContext, user: User | None, session: AsyncSession
) -> None:
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

    # Проверка дубля: нельзя взять дровницу дважды по одному договору в одном месяце
    existing = await RecordRepo(session).find_active(user.telegram_id, text)
    if existing:
        date_str = fmt_dt(existing.created_at)
        await message.answer(
            f"⚠️ Дровница по договору <b>№{text}</b> уже была взята {date_str}.\n\n"
            "Нельзя взять дважды по одному договору в текущем месяце.",
            parse_mode="HTML",
        )
        await state.clear()
        return

    parts = user.full_name.split() if user else []
    first_name = parts[1] if len(parts) >= 2 else (parts[0] if parts else "Сотрудник")
    await state.update_data(site_number=text)
    await message.answer(
        f"Подтвердите получение дровницы:\n\n"
        f"📋 Договор/стройка: <b>{text}</b>\n\n"
        f"📝 Напишите в АМО примечание:\n"
        f"<i>{first_name} взял квоту на дровницу</i>",
        parse_mode="HTML",
        reply_markup=confirm_kb("take"),
    )
    await state.set_state(TakeStates.confirm)


@router.callback_query(TakeStates.confirm, F.data == "confirm:take")
async def take_confirm(
    callback: CallbackQuery,
    state: FSMContext,
    user: User | None,
    is_admin: bool,
    session: AsyncSession,
) -> None:
    if not _require_user(user):
        await callback.answer("Не зарегистрированы", show_alert=True)
        return

    data = await state.get_data()
    site_number = data.get("site_number", "")
    await state.clear()

    user_id = user.telegram_id
    user_role = user.role
    service = QuotaService(session)
    record = await service.take(user, site_number)

    if record is None:
        await callback.message.edit_text("Квота исчерпана. Обратитесь к администратору.")
        await callback.answer()
        return

    status = await service.get_status_for(user_id, user_role)
    await callback.message.edit_text(
        f"✅ Дровница выдана!\n\n"
        f"📋 №{site_number}\n"
        f"📦 Остаток квоты: <b>{status.remaining} из {status.limit}</b>",
        parse_mode="HTML",
    )
    await callback.message.answer("Главное меню:", reply_markup=main_menu_kb(is_admin))
    await callback.answer()


# ---------------------------------------------------------------------------
# Вернуть дровницу (сотрудник — только текущий месяц)
# ---------------------------------------------------------------------------

@router.message(F.text == "↩️ Вернуть дровницу")
async def return_start(message: Message, user: User | None, state: FSMContext) -> None:
    if not _require_user(user):
        await message.answer("Сначала зарегистрируйтесь. Отправьте /start")
        return

    await message.answer(
        "Введите <b>номер договора / стройки</b> дровницы, которую хотите вернуть\n"
        "(только за текущий месяц):",
        parse_mode="HTML",
    )
    await state.set_state(ReturnStates.waiting_site_number)


@router.message(ReturnStates.waiting_site_number)
async def return_site_number(message: Message, state: FSMContext) -> None:
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

    await state.update_data(site_number=text)
    await message.answer(
        f"Вернуть дровницу по договору <b>№{text}</b>?",
        parse_mode="HTML",
        reply_markup=confirm_kb("return"),
    )
    await state.set_state(ReturnStates.confirm)


@router.callback_query(ReturnStates.confirm, F.data == "confirm:return")
async def return_confirm(
    callback: CallbackQuery,
    state: FSMContext,
    user: User | None,
    is_admin: bool,
    session: AsyncSession,
) -> None:
    if not _require_user(user):
        await callback.answer("Не зарегистрированы", show_alert=True)
        return

    data = await state.get_data()
    site_number = data.get("site_number", "")
    await state.clear()

    service = QuotaService(session)
    record = await service.return_own(user, site_number)

    if record is None:
        await callback.message.edit_text(
            f"Запись с договором <b>№{site_number}</b> за текущий месяц не найдена.",
            parse_mode="HTML",
        )
    else:
        status = await service.get_status(user)
        await callback.message.edit_text(
            f"✅ Дровница возвращена!\n\n"
            f"📋 №{site_number}\n"
            f"📦 Остаток квоты: <b>{status.remaining} из {status.limit}</b>",
            parse_mode="HTML",
        )

    await callback.message.answer("Главное меню:", reply_markup=main_menu_kb(is_admin))
    await callback.answer()


# ---------------------------------------------------------------------------
# Отмена FSM (универсальная)
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "cancel")
async def cancel_callback(
    callback: CallbackQuery, state: FSMContext, is_admin: bool
) -> None:
    await state.clear()
    await callback.message.edit_text("Действие отменено.")
    await callback.message.answer("Главное меню:", reply_markup=main_menu_kb(is_admin))
    await callback.answer()


@router.callback_query(F.data == "noop")
async def noop_callback(callback: CallbackQuery) -> None:
    await callback.answer()
