from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.database.base import Base

# Допустимые роли сотрудников
ROLES = ("measurer", "manager", "brigade")
ROLE_LABELS = {
    "measurer": "Замерщик",
    "manager": "Менеджер",
    "brigade": "Бригада",
}


class User(Base):
    __tablename__ = "users"

    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(100))
    phone: Mapped[str] = mapped_column(String(20))
    role: Mapped[str] = mapped_column(String(20))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    records: Mapped[list["Record"]] = relationship(
        back_populates="user", lazy="select", cascade="all, delete-orphan"
    )
    personal_quotas: Mapped[list["Quota"]] = relationship(
        back_populates="user", lazy="select", cascade="all, delete-orphan"
    )


class Quota(Base):
    __tablename__ = "quotas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    role: Mapped[str | None] = mapped_column(String(20), nullable=True)
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"), nullable=True
    )
    monthly_limit: Mapped[int] = mapped_column(Integer)

    user: Mapped["User | None"] = relationship(back_populates="personal_quotas")

    __table_args__ = (
        CheckConstraint(
            "role IS NOT NULL OR user_id IS NOT NULL",
            name="quota_has_target",
        ),
        Index("ix_quotas_user_id", "user_id"),
        Index("ix_quotas_role", "role"),
    )


class Record(Base):
    __tablename__ = "records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE")
    )
    site_number: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    month: Mapped[str] = mapped_column(String(7))  # "2026-02"
    is_cancelled: Mapped[bool] = mapped_column(Boolean, default=False)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped["User"] = relationship(back_populates="records")

    __table_args__ = (
        Index("ix_records_user_month", "user_id", "month"),
        Index("ix_records_site_number", "site_number"),
    )
