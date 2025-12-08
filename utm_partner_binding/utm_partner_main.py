import os
import re
from pathlib import Path
from urllib.parse import parse_qs
from typing import Dict, Literal, Optional

from dotenv import load_dotenv
from fast_bitrix24 import BitrixAsync
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from loguru import logger

# Загружаем переменные окружения
load_dotenv()

app = FastAPI()

# Конфигурация из переменных окружения
WEBHOOK = os.getenv("WEBHOOK")
# Токен для формирования webhook URL из домена хука (опционально)
WEBHOOK_TOKEN = os.getenv("WEBHOOK")
PORT = int(os.getenv("PORT", 8002))
PARTNER_CONTACT_CODE_FIELD = os.getenv("PARTNER_CONTACT_CODE_FIELD", "UF_CRM_1763459353553")
PARTNER_COMPANY_CODE_FIELD = os.getenv("PARTNER_COMPANY_CODE_FIELD", "UF_CRM_1763552640092")
PARTNER_DEAL_REF_DEAL = os.getenv("PARTNER_DEAL_REF_DEAL", "UF_CRM_691F06D06BCAE")
PARTNER_LEAD_REF_LEAD = os.getenv("PARTNER_LEAD_REF_LEAD", "UF_CRM_1763569075")
PARTNER_URLS = os.getenv("PARTNER_URLS", "UF_CRM_1765210560")
# Создаем папку для логов если её нет
logs_dir = Path("logs")
logs_dir.mkdir(exist_ok=True)

# Настройка логирования
logger.add("logs/utm_partner_binding.log", rotation="10 MB", retention="7 days", level="INFO")


async def _parse_request_data(request: Request) -> dict:
    """Парсинг тела запроса: JSON -> form-urlencoded -> raw/querystring.
    Возвращает словарь, гарантируя устойчивость к неверному Content-Type.
    """
    # 1) Попытка JSON
    try:
        return await request.json()
    except Exception:
        pass

    # 2) Попытка form-urlencoded / multipart
    try:
        form = await request.form()
        if form:
            return {k: form.get(k) for k in form.keys()}
    except Exception:
        pass

    # 3) Попытка raw body как form-urlencoded
    try:
        raw = await request.body()
        if raw:
            parsed = parse_qs(raw.decode(errors="ignore"))
            # parse_qs возвращает список значений; берем последнее
            return {k: (v[-1] if isinstance(v, list) and v else v) for k, v in parsed.items()}
    except Exception:
        pass

    # 4) Пусто
    return {}


def _extract_entity_type(document_id_1: str) -> Optional[Literal["deal", "lead"]]:
    """Определение типа сущности по document_id[1]."""
    if not document_id_1:
        return None
    
    document_id_1 = document_id_1.upper()
    if "DEAL" in document_id_1:
        return "deal"
    elif "LEAD" in document_id_1:
        return "lead"
    
    return None


def _extract_entity_id(document_id_2: str) -> Optional[str]:
    """Извлечение ID сущности из document_id[2].
    
    Обрабатывает форматы:
    - 'DEAL_1' -> '1'
    - 'LEAD_1' -> '1'
    - '1' -> '1'
    """
    if not document_id_2:
        return None
    
    # Удаляем префиксы DEAL_ или LEAD_
    entity_id = re.sub(r'^(DEAL_|LEAD_)', '', str(document_id_2).strip(), flags=re.IGNORECASE)
    
    if entity_id and entity_id.isdigit():
        return entity_id
    
    return None


def _get_webhook_url(data: dict) -> Optional[str]:
    """Получение webhook URL из данных хука или переменных окружения.
    
    Пытается сформировать webhook URL из домена хука и токена из .env,
    иначе использует полный webhook URL из .env.
    """
    domain_from_hook = data.get("auth[domain]", "")
    member_id = data.get("auth[member_id]", "")
    
    return WEBHOOK


async def _get_deal_data(deal_id: str, bitrix: BitrixAsync) -> Optional[dict]:
    """Получение данных сделки по ID."""
    try:
        result = await bitrix.call("crm.deal.get", {"ID": deal_id})
        if result.get("order0000000000") is not None:
            result = result.get("order0000000000")
        if result and isinstance(result, dict):
            if "error" in result:
                logger.error(f"Ошибка получения сделки {deal_id}: {result.get('error_description', result.get('error'))}")
                return None
            return result
        
        logger.warning(f"Неожиданный формат ответа при получении сделки {deal_id}: {type(result)}")
        return None
    except Exception as e:
        logger.error(f"Исключение при получении сделки {deal_id}: {e}")
        return None


async def _get_lead_data(lead_id: str, bitrix: BitrixAsync) -> Optional[dict]:
    """Получение данных лида по ID."""
    try:
        result = await bitrix.call("crm.lead.get", {"ID": lead_id})
        if result.get("order0000000000") is not None:
            result = result.get("order0000000000")
        if result and isinstance(result, dict):
            if "error" in result:
                logger.error(f"Ошибка получения лида {lead_id}: {result.get('error_description', result.get('error'))}")
                return None
            return result
        
        logger.warning(f"Неожиданный формат ответа при получении лида {lead_id}: {type(result)}")
        return None
    except Exception as e:
        logger.error(f"Исключение при получении лида {lead_id}: {e}")
        return None


async def _find_partner_by_code(partner_code: str, bitrix: BitrixAsync) -> Optional[Dict[str, str]]:
    """Поиск партнера по коду.
    
    Сначала ищет в контактах, затем в компаниях.
    Возвращает словарь с ключами 'type' ('contact' или 'company') и 'id'.
    """
    if not partner_code:
        return None
    
    partner_code = partner_code.strip()
    if not partner_code:
        return None
    
    logger.info(f"Поиск партнера по коду: {partner_code}")
    
    # Поиск в контактах
    try:
        contact_filter = {
            "filter": {
                PARTNER_CONTACT_CODE_FIELD: partner_code
            },
            "select": ["ID"]
        }
        contacts = await bitrix.get_all("crm.contact.list", params=contact_filter)
        
        if contacts and len(contacts) > 0:
            contact_id = contacts[0].get("ID")
            logger.info(f"Партнер найден в контактах: {contact_id}")
            return {"type": "contact", "id": str(contact_id)}
    except Exception as e:
        logger.error(f"Ошибка поиска партнера в контактах: {e}")
    
    # Поиск в компаниях
    try:
        company_filter = {
            "filter": {
                PARTNER_COMPANY_CODE_FIELD: partner_code
            },
            "select": ["ID"]
        }
        companies = await bitrix.get_all("crm.company.list", params=company_filter)
        
        if companies and len(companies) > 0:
            company_id = companies[0].get("ID")
            logger.info(f"Партнер найден в компаниях: {company_id}")
            return {"type": "company", "id": str(company_id)}
    except Exception as e:
        logger.error(f"Ошибка поиска партнера в компаниях: {e}")
    
    logger.warning(f"Партнер с кодом {partner_code} не найден")
    return None


async def _bind_partner_to_deal(deal_id: str, partner: Dict[str, str], bitrix: BitrixAsync) -> bool:
    """Привязка партнера к сделке."""
    try:
        # Формируем значение привязки
        if partner["type"] == "contact":
            partner_binding = f"C_{partner['id']}"
        else:  # company
            partner_binding = f"CO_{partner['id']}"
        
        logger.info(f"Привязка партнера {partner_binding} к сделке {deal_id}")
        
        update_data = {
            "ID": deal_id,
            "fields": {
                PARTNER_DEAL_REF_DEAL: partner_binding
            }
        }
        
        result = await bitrix.call("crm.deal.update", update_data)
        
        if isinstance(result, bool) and result:
            logger.info(f"Партнер успешно привязан к сделке {deal_id}")
            return True
        elif isinstance(result, dict):
            if "error" in result:
                error_msg = result.get("error_description", result.get("error"))
                logger.error(f"Ошибка привязки партнера к сделке {deal_id}: {error_msg}")
                return False
            elif result.get("result") is True:
                logger.info(f"Партнер успешно привязан к сделке {deal_id}")
                return True
        
        logger.warning(f"Неожиданный ответ при привязке партнера к сделке {deal_id}: {result}")
        return False
    except Exception as e:
        logger.error(f"Исключение при привязке партнера к сделке {deal_id}: {e}")
        return False


async def _bind_partner_to_lead(lead_id: str, partner: Dict[str, str], bitrix: BitrixAsync) -> bool:
    """Привязка партнера к лиду."""
    try:
        # Формируем значение привязки
        if partner["type"] == "contact":
            partner_binding = f"C_{partner['id']}"
        else:  # company
            partner_binding = f"CO_{partner['id']}"
        
        logger.info(f"Привязка партнера {partner_binding} к лиду {lead_id}")
        
        update_data = {
            "ID": lead_id,
            "fields": {
                PARTNER_LEAD_REF_LEAD: partner_binding
            }
        }
        
        result = await bitrix.call("crm.lead.update", update_data)
        
        if isinstance(result, bool) and result:
            logger.info(f"Партнер успешно привязан к лиду {lead_id}")
            return True
        elif isinstance(result, dict):
            if "error" in result:
                error_msg = result.get("error_description", result.get("error"))
                logger.error(f"Ошибка привязки партнера к лиду {lead_id}: {error_msg}")
                return False
            elif result.get("result") is True:
                logger.info(f"Партнер успешно привязан к лиду {lead_id}")
                return True
        
        logger.warning(f"Неожиданный ответ при привязке партнера к лиду {lead_id}: {result}")
        return False
    except Exception as e:
        logger.error(f"Исключение при привязке партнера к лиду {lead_id}: {e}")
        return False


async def _update_contact_partner_code(contact_id: str, partner_code: str, bitrix: BitrixAsync) -> bool:
    """Обновление кода партнера в контакте."""
    try:
        logger.info(f"Обновление кода партнера для контакта {contact_id}: {partner_code}")
        
        update_data = {
            "ID": contact_id,
            "fields": {
                PARTNER_CONTACT_CODE_FIELD: partner_code
            }
        }
        
        result = await bitrix.call("crm.contact.update", update_data)
        
        if isinstance(result, bool) and result:
            logger.info(f"Код партнера успешно обновлен для контакта {contact_id}")
            return True
        elif isinstance(result, dict):
            if "error" in result:
                error_msg = result.get("error_description", result.get("error"))
                logger.error(f"Ошибка обновления кода партнера для контакта {contact_id}: {error_msg}")
                return False
            elif result.get("result") is True:
                logger.info(f"Код партнера успешно обновлен для контакта {contact_id}")
                return True
        
        logger.warning(f"Неожиданный ответ при обновлении кода партнера для контакта {contact_id}: {result}")
        return False
    except Exception as e:
        logger.error(f"Исключение при обновлении кода партнера для контакта {contact_id}: {e}")
        return False


async def _update_company_partner_code(company_id: str, partner_code: str, bitrix: BitrixAsync) -> bool:
    """Обновление кода партнера в компании."""
    try:
        logger.info(f"Обновление кода партнера для компании {company_id}: {partner_code}")
        
        update_data = {
            "ID": company_id,
            "fields": {
                PARTNER_COMPANY_CODE_FIELD: partner_code
            }
        }
        
        result = await bitrix.call("crm.company.update", update_data)
        
        if isinstance(result, bool) and result:
            logger.info(f"Код партнера успешно обновлен для компании {company_id}")
            return True
        elif isinstance(result, dict):
            if "error" in result:
                error_msg = result.get("error_description", result.get("error"))
                logger.error(f"Ошибка обновления кода партнера для компании {company_id}: {error_msg}")
                return False
            elif result.get("result") is True:
                logger.info(f"Код партнера успешно обновлен для компании {company_id}")
                return True
        
        logger.warning(f"Неожиданный ответ при обновлении кода партнера для компании {company_id}: {result}")
        return False
    except Exception as e:
        logger.error(f"Исключение при обновлении кода партнера для компании {company_id}: {e}")
        return False


async def _update_deal_partner_url(deal_id: str, partner_code: str, bitrix: BitrixAsync) -> bool:
    """Обновление поля PARTNER_URLS в сделке с URL партнера."""
    try:
        partner_url = f"https://auto-legal.ru/promo?utm_term={partner_code}"
        logger.info(f"Обновление PARTNER_URLS для сделки {deal_id}: {partner_url}")
        
        update_data = {
            "ID": deal_id,
            "fields": {
                PARTNER_URLS: partner_url
            }
        }
        
        result = await bitrix.call("crm.deal.update", update_data)
        
        if isinstance(result, bool) and result:
            logger.info(f"PARTNER_URLS успешно обновлен для сделки {deal_id}")
            return True
        elif isinstance(result, dict):
            if "error" in result:
                error_msg = result.get("error_description", result.get("error"))
                logger.error(f"Ошибка обновления PARTNER_URLS для сделки {deal_id}: {error_msg}")
                return False
            elif result.get("result") is True:
                logger.info(f"PARTNER_URLS успешно обновлен для сделки {deal_id}")
                return True
        
        logger.warning(f"Неожиданный ответ при обновлении PARTNER_URLS для сделки {deal_id}: {result}")
        return False
    except Exception as e:
        logger.error(f"Исключение при обновлении PARTNER_URLS для сделки {deal_id}: {e}")
        return False


@app.post("/webhook")
async def bitrix24_webhook(request: Request):
    """Обработчик webhook от Bitrix24 для привязки партнеров по UTM меткам."""
    # Парсим данные из запроса
    data = await _parse_request_data(request)
    
    logger.info(f"Получен webhook от Bitrix24: {list(data.keys())}")
    
    # Извлекаем document_id
    document_id_0 = data.get("document_id[0]", "")
    document_id_1 = data.get("document_id[1]", "")
    document_id_2 = data.get("document_id[2]", "")
    
    logger.info(f"document_id[0]={document_id_0}, document_id[1]={document_id_1}, document_id[2]={document_id_2}")
    
    # Определяем тип сущности
    entity_type = _extract_entity_type(document_id_1)
    if not entity_type:
        error_msg = f"Неизвестный тип сущности: {document_id_1}"
        logger.error(error_msg)
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": error_msg}
        )
    
    # Извлекаем ID сущности
    entity_id = _extract_entity_id(document_id_2)
    if not entity_id:
        error_msg = f"Не удалось извлечь ID из document_id[2]: {document_id_2}"
        logger.error(error_msg)
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": error_msg}
        )
    
    logger.info(f"Обработка {entity_type} с ID: {entity_id}")
    
    # Получаем webhook URL
    webhook_url = _get_webhook_url(data)
    if not webhook_url:
        error_msg = "WEBHOOK не задан в хуке и в переменных окружения"
        logger.error(error_msg)
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": error_msg}
        )
    
    # Создаем клиент Bitrix24
    bitrix = BitrixAsync(webhook_url)
    
    # Получаем данные сущности
    if entity_type == "deal":
        entity_data = await _get_deal_data(entity_id, bitrix)
    else:  # lead
        entity_data = await _get_lead_data(entity_id, bitrix)
    
    if not entity_data:
        error_msg = f"Не удалось получить данные {entity_type} с ID {entity_id}"
        logger.error(error_msg)
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": error_msg}
        )
    
    # Извлекаем UTM_TERM
    utm_term = entity_data.get("UTM_TERM", "").strip()
    if not utm_term:
        logger.warning(f"UTM_TERM пустое для {entity_type} {entity_id}")
        return JSONResponse(
            status_code=200,
            content={
                "success": False,
                "message": f"UTM_TERM пустое для {entity_type} {entity_id}",
                "entity_type": entity_type,
                "entity_id": entity_id
            }
        )
    
    logger.info(f"UTM_TERM для {entity_type} {entity_id}: {utm_term}")
    
    # Ищем партнера по коду
    partner = await _find_partner_by_code(utm_term, bitrix)
    if not partner:
        logger.warning(f"Партнер с кодом {utm_term} не найден для {entity_type} {entity_id}")
        return JSONResponse(
            status_code=200,
            content={
                "success": False,
                "message": f"Партнер с кодом {utm_term} не найден",
                "entity_type": entity_type,
                "entity_id": entity_id,
                "partner_code": utm_term
            }
        )
    
    # Привязываем партнера
    if entity_type == "deal":
        success = await _bind_partner_to_deal(entity_id, partner, bitrix)
    else:  # lead
        success = await _bind_partner_to_lead(entity_id, partner, bitrix)
    
    if success:
        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "message": f"Партнер успешно привязан к {entity_type}",
                "entity_type": entity_type,
                "entity_id": entity_id,
                "partner_type": partner["type"],
                "partner_id": partner["id"],
                "partner_code": utm_term
            }
        )
    else:
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": f"Не удалось привязать партнера к {entity_type} {entity_id}",
                "entity_type": entity_type,
                "entity_id": entity_id,
                "partner_type": partner["type"],
                "partner_id": partner["id"]
            }
        )


@app.post("/webhook/deal")
async def deal_webhook(request: Request):
    """Обработчик webhook от Bitrix24 для генерации кода партнера при создании/обновлении сделки."""
    # Парсим данные из запроса
    data = await _parse_request_data(request)
    
    logger.info(f"Получен webhook события сделки: {list(data.keys())}")
    
    # Извлекаем ID сделки из различных возможных форматов webhook
    deal_id = None
    
    # Формат 1: data[FIELDS][ID]
    if "data[FIELDS][ID]" in data:
        deal_id = data.get("data[FIELDS][ID]")
    # Формат 2: data[ID]
    elif "data[ID]" in data:
        deal_id = data.get("data[ID]")
    # Формат 3: document_id[2] (как в основном webhook)
    elif "document_id[2]" in data:
        deal_id = _extract_entity_id(data.get("document_id[2]", ""))
    # Формат 4: FIELDS[ID] (прямой формат)
    elif "FIELDS[ID]" in data:
        deal_id = data.get("FIELDS[ID]")
    # Формат 5: ID (прямой ключ)
    elif "ID" in data:
        deal_id = data.get("ID")
    
    if not deal_id:
        error_msg = "Не удалось извлечь ID сделки из webhook"
        logger.error(f"{error_msg}. Доступные ключи: {list(data.keys())}")
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": error_msg}
        )
    
    logger.info(f"Обработка сделки с ID: {deal_id}")
    
    # Получаем webhook URL
    webhook_url = _get_webhook_url(data)
    if not webhook_url:
        error_msg = "WEBHOOK не задан в хуке и в переменных окружения"
        logger.error(error_msg)
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": error_msg}
        )
    
    # Создаем клиент Bitrix24
    bitrix = BitrixAsync(webhook_url)
    
    # Получаем данные сделки с полями CONTACT_ID и COMPANY_ID
    deal_data = await _get_deal_data(deal_id, bitrix)
    if not deal_data:
        error_msg = f"Не удалось получить данные сделки с ID {deal_id}"
        logger.error(error_msg)
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": error_msg}
        )
    
    results = []
    
    # Обрабатываем контакт, если он привязан
    contact_id = deal_data.get("CONTACT_ID")
    if contact_id:
        contact_id = str(contact_id).strip()
        # Пропускаем пустые значения и "0" (в Bitrix24 "0" означает отсутствие привязки)
        if contact_id and contact_id != "0":
            partner_code = f"ai-{contact_id}"
            success = await _update_contact_partner_code(contact_id, partner_code, bitrix)
            results.append({
                "type": "contact",
                "id": contact_id,
                "partner_code": partner_code,
                "success": success
            })
            logger.info(f"Обработан контакт {contact_id}, код партнера: {partner_code}")
        else:
            logger.debug(f"Контакт не привязан к сделке {deal_id} (CONTACT_ID={contact_id})")
    
    # Обрабатываем компанию, если она привязана
    company_id = deal_data.get("COMPANY_ID")
    if company_id:
        company_id = str(company_id).strip()
        # Пропускаем пустые значения и "0" (в Bitrix24 "0" означает отсутствие привязки)
        if company_id and company_id != "0":
            partner_code = f"ai-{company_id}"
            success = await _update_company_partner_code(company_id, partner_code, bitrix)
            results.append({
                "type": "company",
                "id": company_id,
                "partner_code": partner_code,
                "success": success
            })
            logger.info(f"Обработана компания {company_id}, код партнера: {partner_code}")
        else:
            logger.debug(f"Компания не привязана к сделке {deal_id} (COMPANY_ID={company_id})")
    
    # Если ни контакт, ни компания не привязаны
    if not results:
        logger.warning(f"В сделке {deal_id} не найдены привязанные контакт или компания")
        return JSONResponse(
            status_code=200,
            content={
                "success": False,
                "message": f"В сделке {deal_id} не найдены привязанные контакт или компания",
                "deal_id": deal_id
            }
        )
    
    # Проверяем успешность всех операций
    all_success = all(r["success"] for r in results)
    
    # Обновляем поле PARTNER_URLS в сделке с кодом партнера
    # Приоритет отдаем контакту, если он обработан успешно, иначе используем компанию
    partner_code_for_url = None
    for result in results:
        if result["success"]:
            partner_code_for_url = result["partner_code"]
            # Если это контакт, используем его код (приоритет контакту)
            if result["type"] == "contact":
                break
    
    if partner_code_for_url:
        url_success = await _update_deal_partner_url(deal_id, partner_code_for_url, bitrix)
        if not url_success:
            logger.warning(f"Не удалось обновить PARTNER_URLS для сделки {deal_id}")
    else:
        logger.warning(f"Нет успешно обработанных партнеров для обновления PARTNER_URLS в сделке {deal_id}")
    
    return JSONResponse(
        status_code=200 if all_success else 500,
        content={
            "success": all_success,
            "message": "Коды партнеров успешно обновлены" if all_success else "Частично успешное обновление",
            "deal_id": deal_id,
            "results": results,
            "partner_url_updated": partner_code_for_url is not None
        }
    )


@app.get("/")
async def root():
    """Корневой endpoint для проверки работы сервиса."""
    return JSONResponse(
        content={
            "service": "UTM Partner Binding",
            "status": "running",
            "version": "0.1.0"
        }
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)

