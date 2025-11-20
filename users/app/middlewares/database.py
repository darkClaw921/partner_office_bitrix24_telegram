from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware

from app.db.database import Database


class DatabaseMiddleware(BaseMiddleware):
    """Простая прослойка для проброса подключения к БД в хэндлеры."""

    def __init__(self, db: Database) -> None:
        super().__init__()
        self._db = db

    async def __call__(
        self,
        handler: Callable[[Any, Dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: Dict[str, Any],
    ) -> Any:
        data["db"] = self._db
        return await handler(event, data)