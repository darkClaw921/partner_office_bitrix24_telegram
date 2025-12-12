"""Утилиты для работы с Bitrix24 API."""

from typing import Optional

from fast_bitrix24 import BitrixAsync
from loguru import logger


async def update_deal_utm_term(
    deal_id: str,
    utm_term: str,
    bitrix: BitrixAsync
) -> bool:
    """Обновление UTM метки utm_term в сделке по ID.
    
    Args:
        deal_id: ID сделки
        utm_term: Значение UTM метки для установки
        bitrix: Экземпляр BitrixAsync для работы с API
        
    Returns:
        True если обновление успешно, False в противном случае
    """
    try:
        logger.info(f"Обновление UTM_TERM для сделки {deal_id}: {utm_term}")
        
        update_data = {
            "ID": deal_id,
            "fields": {
                "UTM_TERM": utm_term
            }
        }
        
        result = await bitrix.call("crm.deal.update", update_data)
        
        if isinstance(result, bool) and result:
            logger.info(f"UTM_TERM успешно обновлен для сделки {deal_id}")
            return True
        elif isinstance(result, dict):
            if "error" in result:
                error_msg = result.get("error_description", result.get("error"))
                logger.error(f"Ошибка обновления UTM_TERM для сделки {deal_id}: {error_msg}")
                return False
            elif result.get("result") is True:
                logger.info(f"UTM_TERM успешно обновлен для сделки {deal_id}")
                return True
        
        logger.warning(f"Неожиданный ответ при обновлении UTM_TERM для сделки {deal_id}: {result}")
        return False
    except Exception as e:
        logger.error(f"Исключение при обновлении UTM_TERM для сделки {deal_id}: {e}")
        return False


async def update_lead_utm_term(
    lead_id: str,
    utm_term: str,
    bitrix: BitrixAsync
) -> bool:
    """Обновление UTM метки utm_term в лиде по ID.
    
    Args:
        lead_id: ID лида
        utm_term: Значение UTM метки для установки
        bitrix: Экземпляр BitrixAsync для работы с API
        
    Returns:
        True если обновление успешно, False в противном случае
    """
    try:
        logger.info(f"Обновление UTM_TERM для лида {lead_id}: {utm_term}")
        
        update_data = {
            "ID": lead_id,
            "fields": {
                "UTM_TERM": utm_term
            }
        }
        
        result = await bitrix.call("crm.lead.update", update_data)
        
        if isinstance(result, bool) and result:
            logger.info(f"UTM_TERM успешно обновлен для лида {lead_id}")
            return True
        elif isinstance(result, dict):
            if "error" in result:
                error_msg = result.get("error_description", result.get("error"))
                logger.error(f"Ошибка обновления UTM_TERM для лида {lead_id}: {error_msg}")
                return False
            elif result.get("result") is True:
                logger.info(f"UTM_TERM успешно обновлен для лида {lead_id}")
                return True
        
        logger.warning(f"Неожиданный ответ при обновлении UTM_TERM для лида {lead_id}: {result}")
        return False
    except Exception as e:
        logger.error(f"Исключение при обновлении UTM_TERM для лида {lead_id}: {e}")
        return False




async def get_contact(contact_id, bitrix: BitrixAsync):
    """Получение данных контакта по ID."""
    try:
        result = await bitrix.call('crm.contact.get', {'ID': contact_id})
        if result.get("order0000000000") is not None:
            result = result.get("order0000000000")
        if result and isinstance(result, dict):
            if "error" in result:
                logger.error(f"Ошибка получения контакта {contact_id}: {result.get('error_description', result.get('error'))}")
                return None
            return result
        logger.warning(f"Неожиданный формат ответа при получении контакта {contact_id}: {type(result)}")
        return None
    except Exception as e:
        logger.error(f"Исключение при получении контакта {contact_id}: {e}")
        return None

async def get_company(company_id, bitrix: BitrixAsync):
    """Получение данных компании по ID."""
    try:
        result = await bitrix.call('crm.company.get', {'ID': company_id})
        if result.get("order0000000000") is not None:
            result = result.get("order0000000000")
        if result and isinstance(result, dict):
            if "error" in result:
                logger.error(f"Ошибка получения компании {company_id}: {result.get('error_description', result.get('error'))}")
                return None
            return result
        logger.warning(f"Неожиданный формат ответа при получении компании {company_id}: {type(result)}")
        return None
    except Exception as e:
        logger.error(f"Исключение при получении компании {company_id}: {e}")
        return None



if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    load_dotenv()
    import asyncio
    
    async def main():
        bitrix = BitrixAsync(os.getenv("WEBHOOK"))
        await update_deal_utm_term("22", "12345", bitrix)
        # await update_lead_utm_term("1", "test", bitrix)

    asyncio.run(main())