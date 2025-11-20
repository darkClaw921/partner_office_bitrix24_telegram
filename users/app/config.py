from __future__ import annotations

import json
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
    documents_path: Path | None = None
    documents: list = None
    # Partner field configurations
    partner_contact_code_field: str = "UF_CRM_1763459353553"  # Default value
    partner_company_code_field: str = "UF_CRM_1763552640092"   # Default value
    partner_lead_ref_lead: str = "UF_CRM_1763636439"           # Default value


def _resolve_database_path(raw_path: str | None) -> Path:
    base_path = Path(raw_path or "database.sqlite")
    if not base_path.is_absolute():
        base_path = Path.cwd() / base_path
    base_path.parent.mkdir(parents=True, exist_ok=True)
    return base_path


def _load_documents(documents_path: Path | None) -> list:
    if not documents_path or not documents_path.exists():
        return []
    with open(documents_path, "r", encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    bot_token = os.getenv("BOT_TOKEN")
    if not bot_token:
        raise RuntimeError("BOT_TOKEN не найден в окружении. Добавьте значение в .env")

    db_path = _resolve_database_path(os.getenv("DATABASE_PATH"))
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    bitrix_webhook = os.getenv("BITRIX_WEBHOOK") or os.getenv("WEBHOOK")
    documents_path = Path(os.getenv("DOCUMENTS_PATH", "app/config/documents.json")) if os.getenv("DOCUMENTS_PATH") else None
    documents = _load_documents(documents_path)
    
    # Load Bitrix24 field configurations from environment variables
    partner_contact_code_field = os.getenv("PARTNER_CONTACT_CODE_FIELD", "UF_CRM_1763459353553")
    partner_company_code_field = os.getenv("PARTNER_COMPANY_CODE_FIELD", "UF_CRM_1763552640092")
    partner_lead_ref_lead = os.getenv("PARTNER_LEAD_REF_LEAD", "UF_CRM_1763636439")

    return Settings(
        bot_token=bot_token,
        database_path=db_path,
        log_level=log_level,
        bitrix_webhook=bitrix_webhook,
        documents_path=documents_path,
        documents=documents,
        partner_contact_code_field=partner_contact_code_field,
        partner_company_code_field=partner_company_code_field,
        partner_lead_ref_lead=partner_lead_ref_lead,
    )