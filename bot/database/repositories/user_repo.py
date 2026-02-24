from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import User


class UserRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        result = await self._session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        telegram_id: int,
        full_name: str,
        phone: str,
        role: str,
        is_admin: bool = False,
    ) -> User:
        user = User(
            telegram_id=telegram_id,
            full_name=full_name,
            phone=phone,
            role=role,
            is_admin=is_admin,
        )
        self._session.add(user)
        await self._session.flush()
        return user

    async def set_admin(self, telegram_id: int, is_admin: bool) -> None:
        await self._session.execute(
            update(User)
            .where(User.telegram_id == telegram_id)
            .values(is_admin=is_admin)
        )

    async def get_all(self) -> list[User]:
        result = await self._session.execute(
            select(User).order_by(User.full_name)
        )
        return list(result.scalars().all())

    async def delete(self, telegram_id: int) -> bool:
        user = await self.get_by_telegram_id(telegram_id)
        if not user:
            return False
        await self._session.delete(user)
        await self._session.flush()  # явно отправляем DELETE до коммита
        return True
