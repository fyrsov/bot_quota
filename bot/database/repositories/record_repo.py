from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import Record


def _current_month() -> str:
    return datetime.now().strftime("%Y-%m")


class RecordRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def count_used(self, user_id: int, month: str | None = None) -> int:
        month = month or _current_month()
        result = await self._session.execute(
            select(func.count(Record.id)).where(
                Record.user_id == user_id,
                Record.month == month,
                Record.is_cancelled.is_(False),
            )
        )
        return result.scalar_one()

    async def create(self, user_id: int, site_number: str) -> Record:
        record = Record(
            user_id=user_id,
            site_number=site_number,
            month=_current_month(),
        )
        self._session.add(record)
        await self._session.flush()
        return record

    async def find_active(
        self, user_id: int, site_number: str, month: str | None = None
    ) -> Record | None:
        """Ищет последнюю не отменённую запись за текущий месяц."""
        month = month or _current_month()
        result = await self._session.execute(
            select(Record)
            .where(
                Record.user_id == user_id,
                Record.site_number == site_number,
                Record.month == month,
                Record.is_cancelled.is_(False),
            )
            .order_by(Record.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def cancel(self, record_id: int) -> None:
        await self._session.execute(
            update(Record)
            .where(Record.id == record_id)
            .values(is_cancelled=True)
        )

    async def get_history(
        self, user_id: int, offset: int = 0, limit: int = 30
    ) -> list[Record]:
        """Активные записи пользователя, новые первые."""
        result = await self._session.execute(
            select(Record)
            .where(
                Record.user_id == user_id,
                Record.is_cancelled.is_(False),
            )
            .order_by(Record.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def count_history(self, user_id: int) -> int:
        result = await self._session.execute(
            select(func.count(Record.id)).where(
                Record.user_id == user_id,
                Record.is_cancelled.is_(False),
            )
        )
        return result.scalar_one()

    async def get_by_month_all_users(self, month: str) -> list[Record]:
        """Все активные записи за месяц (для отчёта)."""
        result = await self._session.execute(
            select(Record)
            .where(Record.month == month, Record.is_cancelled.is_(False))
            .order_by(Record.created_at)
        )
        return list(result.scalars().all())

    async def get_stats_months(self) -> list[str]:
        """Список месяцев, в которых есть активные записи."""
        result = await self._session.execute(
            select(Record.month)
            .where(Record.is_cancelled.is_(False))
            .distinct()
            .order_by(Record.month.desc())
        )
        return list(result.scalars().all())

    async def get_by_months(self, months: list[str]) -> list[Record]:
        """Все активные записи за список месяцев (для сводной статистики)."""
        result = await self._session.execute(
            select(Record)
            .where(Record.month.in_(months), Record.is_cancelled.is_(False))
            .order_by(Record.month.desc(), Record.created_at)
        )
        return list(result.scalars().all())

    # --- Для возврата администратором ---
    async def find_active_any_user(
        self, site_number: str, month: str | None = None
    ) -> Record | None:
        month = month or _current_month()
        result = await self._session.execute(
            select(Record)
            .where(
                Record.site_number == site_number,
                Record.month == month,
                Record.is_cancelled.is_(False),
            )
            .order_by(Record.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()
