from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True, slots=True)
class Settings:
    bot_token: str
    database_path: Path
    log_level: str = "INFO"
    bitrix_webhook: str | None = None
    partner_contact_code_field: str = "UF_CRM_1763459353553"
    partner_contact_percent_field: str = "UF_CRM_1763552181843"
    partner_contact_type_id: str = "PARTNER"
    partner_company_code_field: str = "UF_CRM_1763552640092"
    partner_company_percent_field: str = "UF_CRM_1763552607976"
    partner_company_type_id: str = "PARTNER"
    partner_deal_ref_field: str = "UF_CRM_1763470519"


def _resolve_database_path(raw_path: str | None) -> Path:
    base_path = Path(raw_path or "storage/bot.sqlite3")
    if not base_path.is_absolute():
        base_path = Path.cwd() / base_path
    base_path.parent.mkdir(parents=True, exist_ok=True)
    return base_path


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    bot_token = os.getenv("BOT_TOKEN")
    if not bot_token:
        raise RuntimeError("BOT_TOKEN не найден в окружении. Добавьте значение в .env")

    db_path = _resolve_database_path(os.getenv("DATABASE_PATH"))
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    bitrix_webhook = os.getenv("BITRIX_WEBHOOK") or os.getenv("WEBHOOK")
    return Settings(
        bot_token=bot_token,
        database_path=db_path,
        log_level=log_level,
        bitrix_webhook=bitrix_webhook,
        partner_contact_code_field=_clean_env(
            os.getenv("PARTNER_CONTACT_CODE_FIELD"), "UF_CRM_1763459353553"
        ),
        partner_contact_percent_field=_clean_env(
            os.getenv("PARTNER_CONTACT_PERCENT_FIELD"), "UF_CRM_1763552181843"
        ),
        partner_contact_type_id=_clean_env(os.getenv("PARTNER_CONTACT_TYPE_ID"), "PARTNER"),
        partner_company_code_field=_clean_env(
            os.getenv("PARTNER_COMPANY_CODE_FIELD"), "UF_CRM_1763552640092"
        ),
        partner_company_percent_field=_clean_env(
            os.getenv("PARTNER_COMPANY_PERCENT_FIELD"), "UF_CRM_1763552607976"
        ),
        partner_company_type_id=_clean_env(os.getenv("PARTNER_COMPANY_TYPE_ID"), "PARTNER"),
        partner_deal_ref_field=_clean_env(os.getenv("PARTNER_DEAL_REF_DEAL"), "UF_CRM_1763470519"),
    )


def _clean_env(value: str | None, default: str) -> str:
    if value is None:
        return default
    cleaned = value.strip().strip('"').strip("'")
    return cleaned or default

