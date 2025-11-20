from __future__ import annotations

import asyncio

from loguru import logger

from app.bot import create_bot, create_dispatcher
from app.config import get_settings
from app.db.database import Database
from app.logger import setup_logging


async def run_bot() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)

    db = Database(settings.database_path)
    await db.connect()

    bot = create_bot(settings.bot_token)
    dispatcher = create_dispatcher(db)

    logger.info("Старт Telegram-бота")
    try:
        await dispatcher.start_polling(bot, allowed_updates=dispatcher.resolve_used_update_types())
    finally:
        await db.disconnect()
        await bot.session.close()
        logger.info("Telegram-бот остановлен")


def main() -> None:
    asyncio.run(run_bot())


if __name__ == "__main__":
    main()
