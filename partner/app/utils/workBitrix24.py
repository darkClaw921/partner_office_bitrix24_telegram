from __future__ import annotations
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from fast_bitrix24 import BitrixAsync
from loguru import logger

from app.config import Settings, get_settings
from app.utils.helper import format_phone_variants


class BitrixNotConfiguredError(RuntimeError):
    """Выбрасывается, если не задан webhook Bitrix24."""


@dataclass(slots=True)
class PartnerContact:
    id: int
    partner_code: str
    percent: float | None = None


class BitrixService:
    def __init__(self, settings: Settings) -> None:
        if not settings.bitrix_webhook:
            raise BitrixNotConfiguredError("BITRIX_WEBHOOK не задан в окружении")
        self._client = BitrixAsync(settings.bitrix_webhook)
        self._settings = settings

    async def call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        payload = params or {}
        return await self._client.call(method, payload)

    async def get_all(self, method: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        payload = params or {}
        return await self._client.get_all(method, payload)

    async def find_partner_by_phone(self, phone: str) -> PartnerContact | None:
        """
        Поиск партнёра по телефону:
        1. Сначала среди контактов.
        2. Если не найдено — среди компаний.
        """
        phone_variants = format_phone_variants(phone)
        if not phone_variants:
            logger.warning("Bitrix поиск: номер {} не содержит вариантов для фильтра", phone)
            return None

        logger.debug("Bitrix пошаговый поиск партнёра (контакты) по номеру {}", phone)
        contact_partner = await self._find_partner_in_contacts(phone_variants)
        if contact_partner:
            return contact_partner

        logger.debug("Bitrix поиск партнёра (компании) по номеру {}", phone)
        company_partner = await self._find_partner_in_companies(phone_variants)
        if company_partner:
            return company_partner

        return None

    async def _find_partner_in_contacts(self, phone_variants: list[str]) -> PartnerContact | None:
        for variant in phone_variants:
            fields = {
                "select": [
                    "ID",
                    "TYPE_ID",
                    self._settings.partner_contact_code_field,
                    self._settings.partner_contact_percent_field,
                    "PHONE",
                ],
                "filter": {"PHONE": variant},
                "limit": 1,
            }
            contacts = await self.call("crm.contact.list", fields)
            if not contacts:
                continue

            if isinstance(contacts, dict):
                contact = contacts
            elif isinstance(contacts, list):
                contact = contacts[0]
            else:
                logger.warning("Bitrix (contact) вернул неожиданный тип {} для номера {}", type(contacts), variant)
                continue

            if contact.get("TYPE_ID") != self._settings.partner_contact_type_id:
                continue

            partner_code = (contact.get(self._settings.partner_contact_code_field) or "").strip()
            if not partner_code:
                logger.warning(
                    "В контакте {} отсутствует код партнёра {}",
                    contact.get("ID"),
                    self._settings.partner_contact_code_field,
                )
                continue

            return PartnerContact(
                id=int(contact["ID"]),
                partner_code=partner_code,
                percent=_extract_percent(contact.get(self._settings.partner_contact_percent_field)),
            )

        return None

    async def _find_partner_in_companies(self, phone_variants: list[str]) -> PartnerContact | None:
        for variant in phone_variants:
            fields = {
                "select": [
                    "ID",
                    "COMPANY_TYPE",
                    self._settings.partner_company_code_field,
                    self._settings.partner_company_percent_field,
                    "PHONE",
                ],
                "filter": {"PHONE": variant},
                "limit": 1,
            }
            companies = await self.call("crm.company.list", fields)
            if not companies:
                continue

            if isinstance(companies, dict):
                company = companies
            elif isinstance(companies, list):
                company = companies[0]
            else:
                logger.warning("Bitrix (company) вернул неожиданный тип {} для номера {}", type(companies), variant)
                continue

            if company.get("COMPANY_TYPE") != self._settings.partner_company_type_id:
                continue

            partner_code = (company.get(self._settings.partner_company_code_field) or "").strip()
            if not partner_code:
                logger.warning(
                    "В компании {} отсутствует код партнёра {}",
                    company.get("ID"),
                    self._settings.partner_company_code_field,
                )
                continue

            return PartnerContact(
                id=int(company["ID"]),
                partner_code=partner_code,
                percent=_extract_percent(company.get(self._settings.partner_company_percent_field)),
            )

        return None

    async def get_partner_percent(self, contact_id: int) -> float | None:
        payload = {"id": contact_id}
        data = await self.call("crm.contact.get", payload)
        if not data:
            logger.warning("Bitrix: crm.contact.get вернул пустой ответ для contact_id={}", contact_id)
            return None
        return _extract_percent(data.get(self._settings.partner_contact_percent_field))


@lru_cache(maxsize=1)
def get_bitrix_service() -> BitrixService:
    settings = get_settings()
    webhook = getattr(settings, "bitrix_webhook", None)
    if not webhook:
        raise BitrixNotConfiguredError("BITRIX_WEBHOOK не задан в окружении")
    return BitrixService(settings)


async def find_partner_contact_by_phone(phone: str) -> PartnerContact | None:
    service = get_bitrix_service()
    try:
        return await service.find_partner_by_phone(phone)
    except BitrixNotConfiguredError:
        raise
    except Exception:  # noqa: BLE001
        logger.exception("Bitrix: ошибка поиска контакта по номеру {}", phone)
        return None


async def fetch_partner_percent(contact_id: int) -> float | None:
    service = get_bitrix_service()
    try:
        return await service.get_partner_percent(contact_id)
    except BitrixNotConfiguredError:
        raise
    except Exception:  # noqa: BLE001
        logger.exception("Bitrix: ошибка получения процента партнёра {}", contact_id)
        return None


def _extract_percent(value: Any) -> float | None:
    if value in (None, "", []):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        logger.warning("Bitrix: не удалось преобразовать процент партнёра из значения {}", value)
        return None