from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import aiosqlite
from loguru import logger

from app.services.models import PartnerSubmission

SCHEMA = """
CREATE TABLE IF NOT EXISTS partner_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    username TEXT,
    first_name TEXT,
    last_name TEXT,
    phone_number TEXT NOT NULL,
    partner_code TEXT NOT NULL,
    bitrix_contact_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_partner_requests_user ON partner_requests (user_id);
"""


class Database:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._connection: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        if self._connection:
            return

        self._connection = await aiosqlite.connect(self._db_path)
        self._connection.row_factory = aiosqlite.Row
        await self._connection.executescript(SCHEMA)
        await self._ensure_schema()
        await self._connection.commit()
        logger.info("SQLite инициализирован по пути {}", self._db_path)

    async def _ensure_schema(self) -> None:
        assert self._connection is not None
        try:
            await self._connection.execute(
                "ALTER TABLE partner_requests ADD COLUMN bitrix_contact_id INTEGER"
            )
            logger.info("Добавлен столбец bitrix_contact_id в partner_requests")
        except aiosqlite.OperationalError as exc:
            if "duplicate column name" not in str(exc):
                raise
        await self._ensure_unique_user_constraint()

    async def _ensure_unique_user_constraint(self) -> None:
        assert self._connection is not None
        try:
            await self._connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_partner_requests_user ON partner_requests (user_id)"
            )
        except (aiosqlite.OperationalError, aiosqlite.IntegrityError) as exc:
            if "UNIQUE constraint failed" in str(exc):
                logger.warning(
                    "Не удалось создать уникальный индекс для user_id: дубликаты в partner_requests"
                )
            else:
                raise

    async def disconnect(self) -> None:
        if self._connection is None:
            return
        await self._connection.close()
        self._connection = None
        logger.info("SQLite соединение закрыто")

    async def save_submission(self, submission: PartnerSubmission) -> None:
        if self._connection is None:
            raise RuntimeError("Соединение с базой данных не установлено")

        async with self._lock:
            await self._connection.execute(
                """
                INSERT INTO partner_requests (
                    user_id,
                    username,
                    first_name,
                    last_name,
                    phone_number,
                    partner_code,
                    bitrix_contact_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    submission.user_id,
                    submission.username,
                    submission.first_name,
                    submission.last_name,
                    submission.phone_number,
                    submission.partner_code,
                    submission.bitrix_contact_id,
                ),
            )
            await self._connection.commit()
            logger.info(
                "Заявка пользователя {} сохранена (телефон: {}, код: {})",
                submission.user_id,
                submission.phone_number,
                submission.partner_code,
            )

    async def get_submission_by_user(self, user_id: int) -> dict[str, Any] | None:
        if self._connection is None:
            raise RuntimeError("Соединение с базой данных не установлено")

        query = """
            SELECT user_id, username, first_name, last_name, phone_number, partner_code, bitrix_contact_id, created_at
            FROM partner_requests
            WHERE user_id = ?
            LIMIT 1
        """

        async with self._lock:
            async with self._connection.execute(query, (user_id,)) as cursor:
                row = await cursor.fetchone()
        return dict(row) if row else None

    async def fetch_recent_requests(self, limit: int = 10) -> list[dict[str, Any]]:
        if self._connection is None:
            raise RuntimeError("Соединение с базой данных не установлено")

        query = """
            SELECT user_id, username, phone_number, partner_code, bitrix_contact_id, created_at
            FROM partner_requests
            ORDER BY created_at DESC
            LIMIT ?
        """

        async with self._lock:
            async with self._connection.execute(query, (limit,)) as cursor:
                rows = await cursor.fetchall()
        return [dict(row) for row in rows]

