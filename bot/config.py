from datetime import datetime, timedelta, timezone

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    bot_token: str
    admin_ids: str  # "123456789,987654321" — pydantic-settings 2.x не умеет парсить list[int] из CSV
    db_path: str = "data/quota_bot.db"
    tz_offset: int = 3  # UTC+3 (Москва)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    @property
    def admin_id_list(self) -> list[int]:
        return [int(x.strip()) for x in self.admin_ids.split(",") if x.strip()]


settings = Settings()


def fmt_dt(dt: datetime | None, fmt: str = "%d.%m.%Y %H:%M") -> str:
    """Форматирует UTC datetime в локальное время по TZ_OFFSET из настроек."""
    if dt is None:
        return "—"
    local = dt.replace(tzinfo=timezone.utc) + timedelta(hours=settings.tz_offset)
    return local.strftime(fmt)
