from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.keyboards.employee import main_menu_kb

router = Router(name="fallback")


@router.message(Command("menu"))
async def cmd_menu(message: Message, user, is_admin: bool, state: FSMContext) -> None:
    await state.clear()
    if user is not None:
        await message.answer(
            f"👤 {user.full_name} — выберите действие:",
            reply_markup=main_menu_kb(is_admin),
        )
    else:
        await message.answer("Вы не зарегистрированы. Отправьте /start чтобы начать.")


@router.message()
async def fallback(message: Message, user, is_admin: bool, state: FSMContext) -> None:
    current_state = await state.get_state()
    if current_state is not None:
        return  # пользователь в середине FSM — не перебиваем

    if user is not None:
        await message.answer(
            "Используйте кнопки меню или отправьте /menu:",
            reply_markup=main_menu_kb(is_admin),
        )
    else:
        await message.answer("Отправьте /start чтобы зарегистрироваться.")
