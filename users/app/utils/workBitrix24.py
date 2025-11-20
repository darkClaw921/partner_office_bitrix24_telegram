from __future__ import annotations

from typing import Any

from fast_bitrix24 import BitrixAsync
from loguru import logger

from app.config import get_settings
# Removed hardcoded constants as they're now loaded from config

class BitrixNotConfiguredError(RuntimeError):
    """Выбрасывается, если не задан webhook Bitrix24."""


class BitrixService:
    def __init__(self, webhook: str) -> None:
        self._client = BitrixAsync(webhook)
        self.settings = get_settings()

    async def call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        payload = params or {}
        return await self._client.call(method, payload)

    async def find_partner_by_code(self, partner_code: str) -> dict | None:
        """Найти контакт или компанию партнера по коду."""
        # Поиск контакта партнера
        contact_filter = {
            "filter": {
                self.settings.partner_contact_code_field: partner_code
            },
            "select": ["ID"]
        }
        contacts = await self._client.get_all("crm.contact.list", params=contact_filter)
        if contacts:
            return {"type": "contact", "id": contacts[0]["ID"]}
        
        # Если контакт не найден, ищем компанию партнера
        company_filter = {
            "filter": {
                self.settings.partner_company_code_field: partner_code
            },
            "select": ["ID"]
        }
        companies = await self._client.get_all("crm.company.list", params=company_filter)
        if companies:
            return {"type": "company", "id": companies[0]["ID"]}
            
        return None

    async def create_lead(self, title: str, phone: str, partner_code: str, name: str) -> str:
        """Создание лида в Bitrix24 с привязкой к партнеру."""
        # Поиск контакта или компании партнера
        partner = await self.find_partner_by_code(partner_code)
        if not partner:
            logger.warning(f"Контакт или компания партнера с кодом {partner_code} не найден")
        
        fields = {
            "fields": {
                "TITLE": title,
                "NAME": name,  # Добавляем имя в поле NAME лида
                "SOURCE_ID": "TELEGRAM_BOT",  # Источник - Telegram бот
                "STATUS_ID": "NEW",  # Стадия - новая
            },
        }
        
        # Добавляем телефон
        if phone:
            fields["fields"]["PHONE"] = [{"VALUE": phone, "VALUE_TYPE": "WORK"}]
            
        # Добавляем привязку к партнеру через пользовательское поле PARTNER_LEAD_REF_LEAD
        if partner:
            # Формируем значение для пользовательского поля типа "привязка к нескольким элементам CRM"
            # Формат: C_<id> для контакта, CO_<id> для компании
            if partner["type"] == "contact":
                partner_binding = f"C_{partner['id']}"
            else:  # company
                partner_binding = f"CO_{partner['id']}"
            fields["fields"][self.settings.partner_lead_ref_lead] = partner_binding
            logger.info(f"Привязка к партнеру {partner_binding} установлена")

        result = await self.call("crm.lead.add", fields)
        if isinstance(result, int) and result > 0:
            lead_id = str(result)
            logger.info(f"Создан лид {lead_id} для {title} от партнера {partner_code}")
            return lead_id
        elif isinstance(result, dict):
            if "error" in result:
                error_msg = result.get("error_description", str(result["error"]))
                logger.error(f"Ошибка Bitrix API: {error_msg}")
                raise RuntimeError(f"Ошибка создания лида: {error_msg}")
            elif "result" in result:
                lead_id = str(result["result"])
                logger.info(f"Создан лид {lead_id} для {title} от партнера {partner_code}")
                return lead_id
            else:
                logger.error(f"Неожиданный ответ Bitrix: {result}")
                raise RuntimeError(f"Не удалось создать лид: {result}")
        else:
            logger.error(f"Неожиданный тип ответа: {type(result)}, значение: {result}")
            raise RuntimeError(f"Не удалось создать лид: {result}")


def get_bitrix_service():
    settings = get_settings()
    webhook = getattr(settings, "bitrix_webhook", None)
    if not webhook:
        raise BitrixNotConfiguredError("BITRIX_WEBHOOK не задан в окружении")
    return BitrixService(webhook)


async def create_lead(name: str, phone: str, partner_code: str) -> str:
    service = get_bitrix_service()
    try:
        title = f"Консультация: {name}"
        return await service.create_lead(title, phone, partner_code, name)
    except BitrixNotConfiguredError:
        raise
    except Exception as e:  # noqa: BLE001
        logger.exception(f"Bitrix: ошибка создания лида для {name}, {phone}")
        raise RuntimeError(f"Ошибка создания лида: {e}")