import asyncio
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from bot.config import settings
from bot.database.base import AsyncSessionLocal, init_db
from bot.database.repositories.quota_repo import QuotaRepo
from bot.handlers import admin, employee, fallback, onboarding
from bot.middlewares.auth import AuthMiddleware

LOG_DIR = "logs"
LOG_FILE = os.path.join(LOG_DIR, "bot.log")
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

os.makedirs(LOG_DIR, exist_ok=True)

_formatter = logging.Formatter(LOG_FORMAT)

# Вывод в консоль
_console_handler = logging.StreamHandler(sys.stdout)
_console_handler.setFormatter(_formatter)

# Запись в файл: максимум 5 МБ, хранится 5 файлов
_file_handler = RotatingFileHandler(
    LOG_FILE,
    maxBytes=5 * 1024 * 1024,
    backupCount=5,
    encoding="utf-8",
)
_file_handler.setFormatter(_formatter)

logging.basicConfig(level=logging.INFO, handlers=[_console_handler, _file_handler])

# Заглушаем лишний шум от сторонних библиотек
logging.getLogger("aiohttp").setLevel(logging.WARNING)
logging.getLogger("aiogram").setLevel(logging.INFO)

logger = logging.getLogger(__name__)


async def on_startup(bot: Bot) -> None:
    logger.info("Initialising database…")
    await init_db()

    # Засеваем дефолтные квоты по ролям
    async with AsyncSessionLocal() as session:
        repo = QuotaRepo(session)
        await repo.seed_defaults()
        await session.commit()

    # Регистрируем команды — появится кнопка «/» в поле ввода
    await bot.set_my_commands([
        BotCommand(command="start", description="Главное меню"),
        BotCommand(command="menu",  description="Показать меню"),
    ])

    logger.info("Bot started. Admin IDs: %s", settings.admin_id_list)


async def main() -> None:
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    # Middleware применяется ко всем апдейтам
    dp.update.middleware(AuthMiddleware())

    # Порядок важен: admin раньше employee, чтобы фильтр IsAdmin работал корректно
    dp.include_router(onboarding.router)
    dp.include_router(admin.router)
    dp.include_router(employee.router)
    dp.include_router(fallback.router)  # всегда последним

    dp.startup.register(on_startup)

    logger.info("Starting polling…")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()
        logger.info("Bot stopped.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
