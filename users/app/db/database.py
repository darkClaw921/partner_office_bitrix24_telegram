from __future__ import annotations

import aiosqlite
from pathlib import Path
from typing import Any, Optional

from loguru import logger


class Database:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._connection: Optional[aiosqlite.Connection] = None

    async def connect(self) -> None:
        self._connection = await aiosqlite.connect(self.db_path)
        await self.init_schema()
        logger.info(f"Подключение к БД: {self.db_path}")

    async def disconnect(self) -> None:
        if self._connection:
            await self._connection.close()
            self._connection = None
            logger.info("Отключение от БД")

    async def init_schema(self) -> None:
        await self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS user_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE NOT NULL,
                partner_code TEXT NOT NULL,
                name TEXT,
                phone TEXT,
                bitrix_deal_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await self._connection.commit()

        # Уникальный индекс для user_id
        await self._connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_user_requests_user ON user_requests (user_id)")
        await self._connection.commit()

    async def save_request(self, user_id: int, partner_code: str, name: str = None, phone: str = None, bitrix_deal_id: str = None) -> None:
        await self._connection.execute(
            """
            INSERT OR REPLACE INTO user_requests (user_id, partner_code, name, phone, bitrix_deal_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, partner_code, name, phone, bitrix_deal_id),
        )
        await self._connection.commit()
        logger.info(f"Сохранена заявка пользователя {user_id} с кодом партнера {partner_code}")

    async def get_request_by_user(self, user_id: int) -> Optional[dict[str, Any]]:
        await self._connection.execute(
            "SELECT * FROM user_requests WHERE user_id = ? ORDER BY created_at DESC LIMIT 1",
            (user_id,),
        )
        async with self._connection.execute(
            "SELECT * FROM user_requests WHERE user_id = ? ORDER BY created_at DESC LIMIT 1",
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    "id": row[0],
                    "user_id": row[1],
                    "partner_code": row[2],
                    "name": row[3],
                    "phone": row[4],
                    "bitrix_deal_id": row[5],
                    "created_at": row[6],
                }
            return None

    @property
    def connection(self) -> Optional[aiosqlite.Connection]:
        return self._connection