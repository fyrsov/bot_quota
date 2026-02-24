from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import Quota

DEFAULT_LIMIT = 5


class QuotaRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_personal(self, user_id: int) -> Quota | None:
        result = await self._session.execute(
            select(Quota).where(Quota.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_by_role(self, role: str) -> Quota | None:
        result = await self._session.execute(
            select(Quota).where(Quota.role == role, Quota.user_id.is_(None))
        )
        return result.scalar_one_or_none()

    async def get_limit(self, user_id: int, role: str) -> int:
        """Персональная квота имеет приоритет над ролевой."""
        personal = await self.get_personal(user_id)
        if personal is not None:
            return personal.monthly_limit
        role_quota = await self.get_by_role(role)
        if role_quota is not None:
            return role_quota.monthly_limit
        return DEFAULT_LIMIT

    async def set_role_limit(self, role: str, limit: int) -> None:
        existing = await self.get_by_role(role)
        if existing:
            await self._session.execute(
                update(Quota)
                .where(Quota.role == role, Quota.user_id.is_(None))
                .values(monthly_limit=limit)
            )
        else:
            self._session.add(Quota(role=role, monthly_limit=limit))

    async def set_personal_limit(self, user_id: int, limit: int) -> None:
        existing = await self.get_personal(user_id)
        if existing:
            await self._session.execute(
                update(Quota)
                .where(Quota.user_id == user_id)
                .values(monthly_limit=limit)
            )
        else:
            self._session.add(Quota(user_id=user_id, monthly_limit=limit))

    async def remove_personal_limit(self, user_id: int) -> bool:
        quota = await self.get_personal(user_id)
        if not quota:
            return False
        await self._session.delete(quota)
        return True

    async def seed_defaults(self) -> None:
        """Заполняет дефолтные квоты по ролям при первом запуске."""
        from bot.database.models import ROLES

        for role in ROLES:
            existing = await self.get_by_role(role)
            if not existing:
                self._session.add(Quota(role=role, monthly_limit=DEFAULT_LIMIT))
