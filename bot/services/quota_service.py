from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import Record, User
from bot.database.repositories.quota_repo import QuotaRepo
from bot.database.repositories.record_repo import RecordRepo


@dataclass
class QuotaStatus:
    used: int
    limit: int

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)

    @property
    def has_quota(self) -> bool:
        return self.remaining > 0


class QuotaService:
    def __init__(self, session: AsyncSession) -> None:
        self._quota_repo = QuotaRepo(session)
        self._record_repo = RecordRepo(session)

    async def get_status(self, user: User) -> QuotaStatus:
        limit = await self._quota_repo.get_limit(user.telegram_id, user.role)
        used = await self._record_repo.count_used(user.telegram_id)
        return QuotaStatus(used=used, limit=limit)

    async def take(self, user: User, site_number: str) -> Record | None:
        """
        Списывает 1 единицу квоты.
        Возвращает созданную запись или None если квота исчерпана.
        rollback() завершает lazy-транзакцию SQLAlchemy, после чего
        BEGIN IMMEDIATE сериализует конкурентные запросы в SQLite,
        исключая race condition при двойном нажатии.
        """
        session = self._record_repo._session
        await session.rollback()
        await session.execute(text("BEGIN IMMEDIATE"))
        status = await self.get_status(user)
        if not status.has_quota:
            return None
        return await self._record_repo.create(user.telegram_id, site_number)

    async def return_own(self, user: User, site_number: str) -> Record | None:
        """
        Сотрудник возвращает свою дровницу за текущий месяц.
        Возвращает отменённую запись или None если не найдена.
        """
        record = await self._record_repo.find_active(user.telegram_id, site_number)
        if not record:
            return None
        await self._record_repo.cancel(record.id)
        return record

    async def return_admin(self, site_number: str) -> Record | None:
        """
        Администратор возвращает дровницу по номеру договора (любой сотрудник).
        """
        record = await self._record_repo.find_active_any_user(site_number)
        if not record:
            return None
        await self._record_repo.cancel(record.id)
        return record
