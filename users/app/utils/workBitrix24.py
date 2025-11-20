from __future__ import annotations

from typing import Any

from fast_bitrix24 import BitrixAsync
from loguru import logger

from app.config import get_settings
PARTNER_TYPE_ID = "PARTNER"
PARTNER_CODE_FIELD = "UF_CRM_1763459353553"
PARTNER_DEAL_REF_FIELD = "UF_CRM_1763470519"

class BitrixNotConfiguredError(RuntimeError):
    """Выбрасывается, если не задан webhook Bitrix24."""


class BitrixService:
    def __init__(self, webhook: str) -> None:
        self._client = BitrixAsync(webhook)

    async def call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        payload = params or {}
        return await self._client.call(method, payload)

    async def find_or_create_contact(self, name: str, phone: str) -> str:
        """Найти существующий контакт по телефону или создать новый."""
        # Поиск контакта по телефону
        contact_filter = {
            "filter": {
                "PHONE": phone  # Фильтр по номеру телефона
            },
            "select": ["ID", "NAME"]
        }
        contacts = await self._client.get_all("crm.contact.list", params=contact_filter)
        if contacts:
            contact_id = str(contacts[0]["ID"])
            logger.info(f"Найден существующий контакт {contact_id} для {name}, {phone}")
            return contact_id
        else:
            # Создание нового контакта
            new_contact_fields = {
                "fields": {
                    "NAME": name,
                    "PHONE": [{"VALUE": phone, "VALUE_TYPE": "WORK"}]
                }
            }
            result = await self.call("crm.contact.add", new_contact_fields)
            if isinstance(result, int) and result > 0:
                contact_id = str(result)
                logger.info(f"Создан новый контакт {contact_id} для {name}, {phone}")
                return contact_id
            elif isinstance(result, dict) and "result" in result:
                contact_id = str(result["result"])
                logger.info(f"Создан новый контакт {contact_id} для {name}, {phone}")
                return contact_id
            else:
                logger.error(f"Ошибка создания контакта: {result}")
                raise RuntimeError(f"Не удалось создать контакт: {result}")

    async def create_deal(self, title: str, phone: str, partner_code: str, name: str) -> str:
        """Создание сделки в Bitrix24 с привязкой к партнеру и контакту."""
        # Поиск контакта партнера
        partner_filter = {
            "filter": {
                PARTNER_CODE_FIELD: partner_code
            },
            "select": ["ID"]
        }
        partners = await self._client.get_all("crm.contact.list", params=partner_filter)
        if not partners:
            logger.warning(f"Контакт партнера с кодом {partner_code} не найден")
            partner_contact_id = None
        else:
            partner_contact_id = str(partners[0]["ID"])
            logger.info(f"Найден контакт партнера {partner_contact_id} для {partner_code}")

        # Найти или создать контакт клиента
        client_contact_id = await self.find_or_create_contact(name, phone)

        fields = {
            "fields": {
                "TITLE": title,
                "SOURCE_ID": "TELEGRAM_BOT",  # Источник - Telegram бот
                "STAGE_ID": "NEW",  # Стадия - новая
                "CONTACT_ID": client_contact_id,  # Привязка к контакту клиента
            },
        }
        if partner_contact_id:
            fields["fields"][PARTNER_DEAL_REF_FIELD] = partner_contact_id  # Привязка к партнеру
        if phone:
            fields["fields"]["PHONE"] = [{"VALUE": phone, "VALUE_TYPE": "WORK"}]

        result = await self.call("crm.deal.add", fields)
        if isinstance(result, int) and result > 0:
            deal_id = str(result)
            logger.info(f"Создана сделка {deal_id} для {title} от партнера {partner_code}")
            return deal_id
        elif isinstance(result, dict):
            if "error" in result:
                error_msg = result.get("error_description", str(result["error"]))
                logger.error(f"Ошибка Bitrix API: {error_msg}")
                raise RuntimeError(f"Ошибка создания сделки: {error_msg}")
            elif "result" in result:
                deal_id = str(result["result"])
                logger.info(f"Создана сделка {deal_id} для {title} от партнера {partner_code}")
                return deal_id
            else:
                logger.error(f"Неожиданный ответ Bitrix: {result}")
                raise RuntimeError(f"Не удалось создать сделку: {result}")
        else:
            logger.error(f"Неожиданный тип ответа: {type(result)}, значение: {result}")
            raise RuntimeError(f"Не удалось создать сделку: {result}")


def get_bitrix_service():
    settings = get_settings()
    webhook = getattr(settings, "bitrix_webhook", None)
    if not webhook:
        raise BitrixNotConfiguredError("BITRIX_WEBHOOK не задан в окружении")
    return BitrixService(webhook)


async def create_deal(name: str, phone: str, partner_code: str) -> str:
    service = get_bitrix_service()
    try:
        title = f"Консультация: {name}"
        return await service.create_deal(title, phone, partner_code, name)
    except BitrixNotConfiguredError:
        raise
    except Exception as e:  # noqa: BLE001
        logger.exception(f"Bitrix: ошибка создания сделки для {name}, {phone}")
        raise RuntimeError(f"Ошибка создания сделки: {e}")