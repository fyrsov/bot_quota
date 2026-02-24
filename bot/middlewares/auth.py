from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update

from bot.config import settings
from bot.database.base import AsyncSessionLocal
from bot.database.repositories.user_repo import UserRepo


class AuthMiddleware(BaseMiddleware):
    """
    Для каждого апдейта:
    - Открывает сессию БД и кладёт её в data['session']
    - Загружает объект пользователя → data['user'] (None если не зарегистрирован)
    - Устанавливает data['is_admin'] по .env ADMIN_IDS или флагу в БД
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with AsyncSessionLocal() as session:
            data["session"] = session

            telegram_user = data.get("event_from_user")
            if telegram_user:
                repo = UserRepo(session)
                user = await repo.get_by_telegram_id(telegram_user.id)
                data["user"] = user
                data["is_admin"] = (
                    telegram_user.id in settings.admin_id_list
                    or (user is not None and user.is_admin)
                )
            else:
                data["user"] = None
                data["is_admin"] = False

            try:
                result = await handler(event, data)
                await session.commit()
                return result
            except Exception:
                await session.rollback()
                raise
