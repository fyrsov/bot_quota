import re

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import ROLE_LABELS
from bot.database.repositories.user_repo import UserRepo
from bot.config import settings
from bot.keyboards.employee import main_menu_kb, role_selection_kb
from bot.states.onboarding import OnboardingStates

router = Router(name="onboarding")

# --- Валидация ---
_NAME_RE = re.compile(r"^[А-ЯЁа-яёA-Za-z\s\-]{2,100}$")
_PHONE_RE = re.compile(r"^\+?[\d\s\-\(\)]{7,20}$")
_MAX_FIELD_LEN = 100


@router.message(CommandStart())
async def cmd_start(message: Message, user, is_admin: bool, state: FSMContext) -> None:
    await state.clear()

    if user is not None:
        await message.answer(
            f"С возвращением, {user.full_name}!\n"
            f"Роль: {ROLE_LABELS.get(user.role, user.role)}",
            reply_markup=main_menu_kb(is_admin),
        )
        return

    await message.answer(
        "Добро пожаловать! Для начала работы нужно зарегистрироваться.\n\n"
        "Введите ваше <b>ФИО</b> (Фамилия Имя Отчество):",
        parse_mode="HTML",
    )
    await state.set_state(OnboardingStates.waiting_full_name)


@router.message(OnboardingStates.waiting_full_name)
async def process_full_name(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()

    if not text or len(text) > _MAX_FIELD_LEN:
        await message.answer("Введите ФИО (не более 100 символов):")
        return
    if not _NAME_RE.match(text):
        await message.answer("ФИО должно содержать только буквы, пробелы и дефисы.\nПопробуйте ещё раз:")
        return

    await state.update_data(full_name=text)
    await message.answer("Введите ваш <b>номер телефона</b>:", parse_mode="HTML")
    await state.set_state(OnboardingStates.waiting_phone)


@router.message(OnboardingStates.waiting_phone)
async def process_phone(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()

    if not text or len(text) > 20:
        await message.answer("Введите номер телефона (не более 20 символов):")
        return
    if not _PHONE_RE.match(text):
        await message.answer(
            "Некорректный номер телефона. Введите в формате +7XXXXXXXXXX или 8XXXXXXXXXX:"
        )
        return

    await state.update_data(phone=text)
    await message.answer(
        "Выберите вашу <b>должность</b>:",
        parse_mode="HTML",
        reply_markup=role_selection_kb(),
    )
    await state.set_state(OnboardingStates.waiting_role)


@router.callback_query(OnboardingStates.waiting_role, F.data.startswith("role:"))
async def process_role(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    is_admin: bool,
) -> None:
    role = callback.data.split(":")[1]
    if role not in ("measurer", "manager", "brigade"):
        await callback.answer("Неверный выбор", show_alert=True)
        return

    data = await state.get_data()
    repo = UserRepo(session)

    # Проверяем, что пользователь ещё не зарегистрирован (защита от дублей)
    existing = await repo.get_by_telegram_id(callback.from_user.id)
    if existing:
        await state.clear()
        await callback.message.edit_text("Вы уже зарегистрированы.")
        await callback.message.answer("Главное меню:", reply_markup=main_menu_kb(is_admin))
        await callback.answer()
        return

    user = await repo.create(
        telegram_id=callback.from_user.id,
        full_name=data["full_name"],
        phone=data["phone"],
        role=role,
        is_admin=callback.from_user.id in settings.admin_id_list,
    )
    await state.clear()

    await callback.message.edit_text(
        f"Регистрация завершена!\n\n"
        f"👤 {user.full_name}\n"
        f"📱 {user.phone}\n"
        f"💼 {ROLE_LABELS[role]}"
    )
    await callback.message.answer(
        "Добро пожаловать! Выберите действие:",
        reply_markup=main_menu_kb(is_admin),
    )
    await callback.answer()


