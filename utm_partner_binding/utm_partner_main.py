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
        print(result)
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

