import json
import os
from urllib.parse import parse_qs
from typing import Dict

from dotenv import load_dotenv
from fast_bitrix24 import BitrixAsync
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from loguru import logger

# Загружаем переменные окружения
load_dotenv()

app = FastAPI()

# Получаем название поля из переменных окружения
PARTNER_DEAL_REF_FIELD = os.getenv("PARTNER_DEAL_REF_DEAL", "UF_CRM_1763470519")
PARTNER_LEAD_REF_FIELD = os.getenv("PARTNER_LEAD_REF_LEAD", "UF_CRM_1763569075")
PARTNER_IS_PAYMENT_FIELD = os.getenv("PARTNER_IS_PAYMENT", "UF_CRM_1765211983998")
PARTNER_COMPANY_PERCENT_FIELD = os.getenv("PARTNER_COMPANY_PERCENT_FIELD", "UF_CRM_1763568055347")
PARTNER_CONTACT_PERCENT_FIELD = os.getenv("PARTNER_CONTACT_PERCENT_FIELD", "UF_CRM_1763569663555")

domain=os.getenv("WEBHOOK").split("/")[2]

# Кэш для статусов воронок и лидов
_stage_cache: Dict[str, Dict[str, str]] = {}
_lead_status_cache: Dict[str, str] = {}
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


async def get_deal_stages(category_id: str, bitrix: BitrixAsync) -> Dict[str, str]:
    """
    Получение статусов сделок для указанной воронки.
    
    Args:
        category_id: ID воронки (0 для основной воронки)
        bitrix: Экземпляр BitrixAsync
        
    Returns:
        Словарь {STAGE_ID: название стадии}
    """
    global _stage_cache
    
    # Формируем entityId: для воронки 0 - DEAL_STAGE, для других - DEAL_STAGE_<id>
    if not category_id or category_id == "0" or category_id == 0 or str(category_id).strip() == "":
        entity_id = "DEAL_STAGE"
    else:
        entity_id = f"DEAL_STAGE_{category_id}"
    
    # Проверяем кэш
    if entity_id in _stage_cache:
        return _stage_cache[entity_id]
    
    try:
        logger.info(f"Получение статусов для воронки {category_id} (entityId: {entity_id})")
        stages = await bitrix.get_all("crm.status.entity.items", {"entityId": entity_id})
        
        if stages and isinstance(stages, list):
            stage_map = {}
            
            for stage in stages:
                stage_id = stage.get("STATUS_ID", "")
                stage_name = stage.get("NAME", stage_id)
                if stage_id:
                    stage_map[stage_id] = stage_name
            
            # Сохраняем в кэш
            _stage_cache[entity_id] = stage_map
            logger.info(f"Получено {len(stage_map)} статусов для воронки {category_id} (entityId: {entity_id})")
            return stage_map
        else:
            logger.warning(f"Не удалось получить статусы для воронки {category_id}: пустой результат")
            return {}
            
    except Exception as e:
        logger.error(f"Ошибка получения статусов для воронки {category_id}: {e}")
        return {}


async def get_contact_info(contact_id: str, bitrix: BitrixAsync) -> dict:
    """
    Получение информации о контакте.
    
    Args:
        contact_id: ID контакта
        bitrix: Экземпляр BitrixAsync
        
    Returns:
        Информация о контакте
    """
    try:
        result = await bitrix.call("crm.contact.get", {"ID": contact_id})
        
        if result and isinstance(result, dict):
            # Битрикс может вернуть данные в обертке
            contact_data = result.get('order0000000000', result)
            
            if contact_data and "error" not in contact_data:
                name_parts = []
                if contact_data.get("NAME"):
                    name_parts.append(contact_data["NAME"])
                if contact_data.get("LAST_NAME"):
                    name_parts.append(contact_data["LAST_NAME"])
                
                # Получаем процент партнера
                partner_percent = contact_data.get(PARTNER_CONTACT_PERCENT_FIELD, "0")
                try:
                    partner_percent = float(partner_percent) if partner_percent else 0.0
                except (ValueError, TypeError):
                    partner_percent = 0.0
                
                return {
                    "id": contact_id,
                    "name": " ".join(name_parts) or f"Контакт #{contact_id}",
                    "partner_percent": partner_percent
                }
        
        return {"id": contact_id, "name": f"Контакт #{contact_id}", "partner_percent": 0.0}
                
    except Exception as e:
        logger.error(f"Ошибка получения данных контакта #{contact_id}: {e}")
        return {"id": contact_id, "name": f"Контакт #{contact_id}", "partner_percent": 0.0}


async def get_company_info(company_id: str, bitrix: BitrixAsync) -> dict:
    """
    Получение информации о компании.
    
    Args:
        company_id: ID компании
        bitrix: Экземпляр BitrixAsync
        
    Returns:
        Информация о компании
    """
    try:
        result = await bitrix.call("crm.company.get", {"ID": company_id})
        
        if result and isinstance(result, dict):
            # Битрикс может вернуть данные в обертке
            company_data = result.get('order0000000000', result)
            
            if company_data and "error" not in company_data:
                # Получаем процент партнера
                partner_percent = company_data.get(PARTNER_COMPANY_PERCENT_FIELD, "0")
                try:
                    partner_percent = float(partner_percent) if partner_percent else 0.0
                except (ValueError, TypeError):
                    partner_percent = 0.0
                
                return {
                    "id": company_id,
                    "name": company_data.get("TITLE", f"Компания #{company_id}"),
                    "partner_percent": partner_percent
                }
        
        return {"id": company_id, "name": f"Компания #{company_id}", "partner_percent": 0.0}
                
    except Exception as e:
        logger.error(f"Ошибка получения данных компании #{company_id}: {e}")
        return {"id": company_id, "name": f"Компания #{company_id}", "partner_percent": 0.0}


async def get_contact_deals(contact_id: str, bitrix: BitrixAsync, domain: str = "") -> list[dict]:
    """
    Получение всех сделок, где контакт указан в поле PARTNER_DEAL_REF_FIELD.
    
    Args:
        contact_id: ID контакта
        bitrix: Экземпляр BitrixAsync
        domain: Домен Битрикс24 для создания ссылок
        
    Returns:
        Список сделок
    """
    try:
        # Формируем значение фильтра в формате C_{contact_id}
        partner_binding = f"C_{contact_id}"
        
        # Фильтр для поиска сделок
        filter_payload = {PARTNER_DEAL_REF_FIELD: partner_binding}
        
        logger.info(f"Поиск сделок с фильтром: {filter_payload}")
        
        # Получаем все сделки
        deals = await bitrix.get_all(
            "crm.deal.list",
            params={
                "filter": filter_payload,
                "select": [
                    "ID",
                    "TITLE",
                    "STAGE_ID",
                    "CATEGORY_ID",
                    "OPPORTUNITY",
                    "CURRENCY_ID",
                    "DATE_CREATE",
                    "COMPANY_ID",
                    "CONTACT_ID",
                    PARTNER_IS_PAYMENT_FIELD
                ]
            }
        )
        
        logger.info(f"Найдено сделок: {len(deals) if deals else 0}")
        
        return deals if deals else []
                
    except Exception as e:
        logger.error(f"Ошибка получения сделок для контакта #{contact_id}: {e}")
        return []


async def get_company_deals(company_id: str, bitrix: BitrixAsync, domain: str = "") -> list[dict]:
    """
    Получение всех сделок, где компания указана в поле PARTNER_DEAL_REF_FIELD.
    
    Args:
        company_id: ID компании
        bitrix: Экземпляр BitrixAsync
        domain: Домен Битрикс24 для создания ссылок
        
    Returns:
        Список сделок
    """
    try:
        # Формируем значение фильтра в формате CO_{company_id}
        partner_binding = f"CO_{company_id}"
        
        # Фильтр для поиска сделок
        filter_payload = {PARTNER_DEAL_REF_FIELD: partner_binding}
        
        logger.info(f"Поиск сделок с фильтром: {filter_payload}")
        
        # Получаем все сделки
        deals = await bitrix.get_all(
            "crm.deal.list",
            params={
                "filter": filter_payload,
                "select": [
                    "ID",
                    "TITLE",
                    "STAGE_ID",
                    "CATEGORY_ID",
                    "OPPORTUNITY",
                    "CURRENCY_ID",
                    "DATE_CREATE",
                    "COMPANY_ID",
                    "CONTACT_ID",
                    PARTNER_IS_PAYMENT_FIELD
                ]
            }
        )
        
        logger.info(f"Найдено сделок: {len(deals) if deals else 0}")
        
        return deals if deals else []
                
    except Exception as e:
        logger.error(f"Ошибка получения сделок для компании #{company_id}: {e}")
        return []


async def get_lead_statuses(bitrix: BitrixAsync) -> Dict[str, str]:
    """
    Получение статусов лидов.
    
    Args:
        bitrix: Экземпляр BitrixAsync
        
    Returns:
        Словарь {STATUS_ID: название статуса}
    """
    global _lead_status_cache
    
    # Проверяем кэш
    if _lead_status_cache:
        return _lead_status_cache
    
    try:
        logger.info("Получение статусов лидов")
        # Для лидов используется entityId: "STATUS"
        statuses = await bitrix.get_all("crm.status.entity.items", {"entityId": "STATUS"})
        
        if statuses and isinstance(statuses, list):
            status_map = {}
            
            for status in statuses:
                status_id = status.get("STATUS_ID", "")
                status_name = status.get("NAME", status_id)
                if status_id:
                    status_map[status_id] = status_name
            
            # Сохраняем в кэш
            _lead_status_cache = status_map
            logger.info(f"Получено {len(status_map)} статусов лидов")
            return status_map
        else:
            logger.warning("Не удалось получить статусы лидов: пустой результат")
            return {}
            
    except Exception as e:
        logger.error(f"Ошибка получения статусов лидов: {e}")
        return {}


async def get_contact_leads(contact_id: str, bitrix: BitrixAsync, domain: str = "") -> list[dict]:
    """
    Получение всех лидов, где контакт указан в поле PARTNER_LEAD_REF_FIELD.
    
    Args:
        contact_id: ID контакта
        bitrix: Экземпляр BitrixAsync
        domain: Домен Битрикс24 для создания ссылок
        
    Returns:
        Список лидов
    """
    try:
        # Формируем значение фильтра в формате C_{contact_id}
        partner_binding = f"C_{contact_id}"
        
        # Фильтр для поиска лидов
        filter_payload = {PARTNER_LEAD_REF_FIELD: partner_binding}
        
        logger.info(f"Поиск лидов с фильтром: {filter_payload}")
        
        # Получаем все лиды
        leads = await bitrix.get_all(
            "crm.lead.list",
            params={
                "filter": filter_payload,
                "select": [
                    "ID",
                    "TITLE",
                    "STATUS_ID",
                    "OPPORTUNITY",
                    "CURRENCY_ID",
                    "DATE_CREATE",
                    "COMPANY_ID",
                    "CONTACT_ID"
                ]
            }
        )
        
        logger.info(f"Найдено лидов: {len(leads) if leads else 0}")
        
        return leads if leads else []
                
    except Exception as e:
        logger.error(f"Ошибка получения лидов для контакта #{contact_id}: {e}")
        return []


async def get_company_leads(company_id: str, bitrix: BitrixAsync, domain: str = "") -> list[dict]:
    """
    Получение всех лидов, где компания указана в поле PARTNER_LEAD_REF_FIELD.
    
    Args:
        company_id: ID компании
        bitrix: Экземпляр BitrixAsync
        domain: Домен Битрикс24 для создания ссылок
        
    Returns:
        Список лидов
    """
    try:
        # Формируем значение фильтра в формате CO_{company_id}
        partner_binding = f"CO_{company_id}"
        
        # Фильтр для поиска лидов
        filter_payload = {PARTNER_LEAD_REF_FIELD: partner_binding}
        
        logger.info(f"Поиск лидов с фильтром: {filter_payload}")
        
        # Получаем все лиды
        leads = await bitrix.get_all(
            "crm.lead.list",
            params={
                "filter": filter_payload,
                "select": [
                    "ID",
                    "TITLE",
                    "STATUS_ID",
                    "OPPORTUNITY",
                    "CURRENCY_ID",
                    "DATE_CREATE",
                    "COMPANY_ID",
                    "CONTACT_ID"
                ]
            }
        )
        
        logger.info(f"Найдено лидов: {len(leads) if leads else 0}")
        
        return leads if leads else []
                
    except Exception as e:
        logger.error(f"Ошибка получения лидов для компании #{company_id}: {e}")
        return []


def format_currency(amount: float, currency: str = "RUB") -> str:
    """Форматирование суммы с валютой."""
    currency_symbols = {
        "RUB": "₽",
        "USD": "$",
        "EUR": "€"
    }
    symbol = currency_symbols.get(currency, currency)
    return f"{amount:,.0f} {symbol}".replace(",", " ")


@app.post("/webhook", response_class=HTMLResponse)
async def bitrix24_webhook(request: Request):
    """
    Обработчик webhook от Битрикс24 для карточки контакта или компании.
    Получает данные о контакте/компании и отображает все сделки, где контакт/компания указан как партнер.
    
    Пример входных данных:
    {
        'AUTH_EXPIRES': '3600',
        'AUTH_ID': '3887b068007b96ee007b49e800000001000007c425c8345a9600bd3f00fed57371e6',
        'PLACEMENT': 'CRM_CONTACT_DETAIL_TAB' или 'CRM_COMPANY_DETAIL_TAB',
        'PLACEMENT_OPTIONS': '{"ID":"123"}',
        'REFRESH_ID': '2806d868007b96ee007b49e800000001000007224ba3bff481836412123c08db5986e9',
        'member_id': '48620745570fb488aebad2cc4f4b9072',
        'status': 'L'
    }
    """
    # Парсим данные из запроса
    data = await _parse_request_data(request)
    
    logger.info(f"Получен webhook от Битрикс24: {data}")
    
    # Определяем тип размещения
    placement = data.get('PLACEMENT', 'CRM_CONTACT_DETAIL_TAB')
    
    # Извлекаем PLACEMENT_OPTIONS
    placement_options = data.get('PLACEMENT_OPTIONS', '{}')
    
    # Если данные в формате строки JSON - парсим
    if isinstance(placement_options, str):
        try:
            placement_options = json.loads(placement_options)
        except json.JSONDecodeError:
            logger.warning(f"Не удалось распарсить PLACEMENT_OPTIONS: {placement_options}")
            placement_options = {}
    
    # Получаем ID контакта или компании
    entity_id = placement_options.get('ID', 'unknown')
    
    if entity_id == 'unknown':
        logger.error("Не удалось получить ID контакта или компании")
        return HTMLResponse(
            content="<h1>Ошибка</h1><p>Не удалось получить ID контакта или компании</p>",
            status_code=400
        )
    
    # Получаем webhook URL из переменных окружения
    webhook_url = os.getenv("WEBHOOK")
    
    if not webhook_url:
        logger.error("WEBHOOK не задан в .env")
        return HTMLResponse(
            content="<h1>Ошибка</h1><p>WEBHOOK не настроен</p>",
            status_code=500
        )
    
    # Создаем клиент Битрикс24
    bitrix = BitrixAsync(webhook_url)
    
    # Получаем информацию о контакте или компании
    if placement == 'CRM_CONTACT_DETAIL_TAB':
        entity_info = await get_contact_info(entity_id, bitrix)
        # Получаем все сделки и лиды контакта
        deals = await get_contact_deals(entity_id, bitrix, domain)
        leads = await get_contact_leads(entity_id, bitrix, domain)
        entity_type = "контакта"
    elif placement == 'CRM_COMPANY_DETAIL_TAB':
        entity_info = await get_company_info(entity_id, bitrix)
        # Получаем все сделки и лиды компании
        deals = await get_company_deals(entity_id, bitrix, domain)
        leads = await get_company_leads(entity_id, bitrix, domain)
        entity_type = "компании"
    else:
        logger.error(f"Неизвестный тип размещения: {placement}")
        return HTMLResponse(
            content="<h1>Ошибка</h1><p>Неизвестный тип размещения</p>",
            status_code=400
        )
    
    # Получаем домен из данных запроса
    member_id = data.get('member_id', '')
    
    # Получаем статусы для всех уникальных воронок
    category_ids = set()
    for deal in deals:
        category_id = deal.get("CATEGORY_ID", "0")
        category_ids.add(str(category_id))
    
    # Загружаем статусы для всех воронок
    stages_map: Dict[str, Dict[str, str]] = {}
    for cat_id in category_ids:
        stages_map[cat_id] = await get_deal_stages(cat_id, bitrix)
    
    # Получаем статусы лидов
    lead_statuses = await get_lead_statuses(bitrix)
    
    # Рассчитываем статистику по сделкам
    partner_percent = entity_info.get("partner_percent", 0.0)
    success_amount = 0.0
    in_progress_amount = 0.0
    paid_amount = 0.0
    success_count = 0
    in_progress_count = 0
    default_currency = "RUB"
    
    for deal in deals:
        amount = float(deal.get("OPPORTUNITY", 0))
        stage_id = deal.get("STAGE_ID", "").upper()
        # Поле PARTNER_IS_PAYMENT принимает значения "0" или "1"
        is_payment = deal.get(PARTNER_IS_PAYMENT_FIELD, "0")
        currency = deal.get("CURRENCY_ID", "RUB")
        if not default_currency or default_currency == "RUB":
            default_currency = currency
        
        # Проверяем статус выплаты (для всех сделок с выплатой)
        # Поле PARTNER_IS_PAYMENT принимает значения "0" или "1"
        if is_payment == "1":
            paid_amount += amount * (partner_percent / 100) if partner_percent > 0 else 0
        
        # Классифицируем сделки
        if "WON" in stage_id or "SUCCESS" in stage_id:
            success_amount += amount
            success_count += 1
        elif "LOSE" not in stage_id and "FAIL" not in stage_id:
            in_progress_amount += amount
            in_progress_count += 1
    
    # Формируем HTML со списком сделок
    deals_html = ""
    if deals:
        for deal in deals:
            deal_id = deal.get("ID", "")
            title = deal.get("TITLE", f"Сделка #{deal_id}")
            amount = float(deal.get("OPPORTUNITY", 0))
            currency = deal.get("CURRENCY_ID", "RUB")
            stage_id = deal.get("STAGE_ID", "")
            category_id = str(deal.get("CATEGORY_ID", "0"))
            # Поле PARTNER_IS_PAYMENT принимает значения "0" или "1"
            is_payment = deal.get(PARTNER_IS_PAYMENT_FIELD, "0")
            
            # Проверяем статус выплаты
            is_payment_bool = is_payment == "1"
            
            # Получаем название стадии
            stage_name = stages_map.get(category_id, {}).get(stage_id, stage_id)

            # Формируем ссылку на сделку
            deal_url = f"https://{domain}/crm/deal/details/{deal_id}/" if member_id else "#"
            
            # Определяем цвет стадии
            stage_color = "#3498db"  # По умолчанию синий
            is_success = "WON" in stage_id.upper() or "SUCCESS" in stage_id.upper()
            if is_success:
                stage_color = "#2ecc71"  # Зеленый для выигранных
            elif "LOSE" in stage_id.upper() or "FAIL" in stage_id.upper():
                stage_color = "#e74c3c"  # Красный для проигранных
            
            # Рассчитываем сумму к выплате на основе процента партнера
            payment_amount = amount * (partner_percent / 100) if partner_percent > 0 else 0
            
            # Кнопка выплаты (показывается для всех сделок, где выплата не произведена)
            payment_button_html = ""
            if not is_payment_bool:
                payment_button_html = f"""
                <button class="payment-button" onclick="markPaymentDone(event, '{deal_id}', {amount}, {partner_percent})">
                    ✓ Выплата 
                </button>
                """
            else:
                payment_button_html = """
                <span class="payment-done">✓ Выплачено</span>
                """
            
            deals_html += f"""
            <div class="deal-card-wrapper" data-deal-id="{deal_id}" data-deal-amount="{amount}">
                <div class="deal-card">
                    <a href="{deal_url}" class="deal-card-link" target="_blank">
                        <div class="deal-content">
                            <div class="deal-header">
                                <div class="deal-title">{title}</div>
                            </div>
                            <div class="deal-meta">
                                <span class="deal-id">ID: {deal_id}</span>
                                <span class="deal-stage" style="background-color: {stage_color}20; color: {stage_color};">
                                    {stage_name}
                                </span>
                            </div>
                        </div>
                    </a>
                    <div class="deal-payment-section">
                        <div class="deal-payment">
                            {payment_button_html}
                        </div>
                        <div class="deal-amount">{format_currency(payment_amount, currency)}</div>
                    </div>
                </div>
            </div>
            """
    else:
        deals_html = """
        <div class="no-deals">
            <p>📋 Сделок не найдено</p>
            <p class="hint">У этой сущности пока нет сделок в качестве партнера</p>
        </div>
        """
    
    # Формируем HTML со списком лидов
    leads_html = ""
    if leads:
        for lead in leads:
            lead_id = lead.get("ID", "")
            title = lead.get("TITLE", f"Лид #{lead_id}")
            amount = float(lead.get("OPPORTUNITY", 0))
            currency = lead.get("CURRENCY_ID", "RUB")
            status_id = lead.get("STATUS_ID", "")
            
            # Получаем название статуса
            status_name = lead_statuses.get(status_id, status_id)

            # Формируем ссылку на лид
            lead_url = f"https://{domain}/crm/lead/details/{lead_id}/" if member_id else "#"
            
            # Определяем цвет статуса
            status_color = "#3498db"  # По умолчанию синий
            if "CONVERTED" in status_id.upper() or "SUCCESS" in status_id.upper():
                status_color = "#2ecc71"  # Зеленый для конвертированных
            elif "JUNK" in status_id.upper() or "FAIL" in status_id.upper():
                status_color = "#e74c3c"  # Красный для некачественных
            
            leads_html += f"""
            <a href="{lead_url}" class="deal-card-link" target="_blank">
                <div class="deal-card">
                    <div class="deal-header">
                        <div class="deal-title">{title}</div>
                        <div class="deal-amount">{format_currency(amount, currency)}</div>
                    </div>
                    <div class="deal-meta">
                        <span class="deal-id">ID: {lead_id}</span>
                    <span class="deal-stage" style="background-color: {status_color}20; color: {status_color};">
                        {status_name}
                    </span>
                    </div>
                </div>
            </a>
            """
    else:
        leads_html = """
        <div class="no-deals">
            <p>📋 Лидов не найдено</p>
            <p class="hint">У этой сущности пока нет лидов в качестве партнера</p>
        </div>
        """
    
    # Формируем HTML ответ
    html_content = f"""
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Сделки партнера</title>
        <style>
            * {{
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }}
            
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
                background: #f8f9fa;
                padding: 20px;
            }}
            
            .header {{
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                padding: 24px;
                border-radius: 12px;
                margin-bottom: 24px;
                box-shadow: 0 4px 12px rgba(102, 126, 234, 0.3);
            }}
            
            .header h1 {{
                font-size: 24px;
                font-weight: 600;
                margin-bottom: 8px;
            }}
            
            .header p {{
                opacity: 0.9;
                font-size: 14px;
            }}
            
            .header-stats {{
                margin-top: 16px;
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                gap: 16px;
            }}
            
            .stat-item {{
                background: rgba(255, 255, 255, 0.15);
                padding: 12px;
                border-radius: 8px;
                backdrop-filter: blur(10px);
            }}
            
            .stat-label {{
                font-size: 12px;
                opacity: 0.8;
                margin-bottom: 4px;
            }}
            
            .stat-value {{
                font-size: 18px;
                font-weight: 600;
            }}
            
            .accordion {{
                margin-bottom: 16px;
            }}
            
            .accordion-item {{
                background: white;
                border-radius: 12px;
                margin-bottom: 12px;
                box-shadow: 0 2px 8px rgba(0,0,0,0.05);
                overflow: hidden;
            }}
            
            .accordion-header {{
                padding: 20px;
                cursor: pointer;
                display: flex;
                justify-content: space-between;
                align-items: center;
                transition: background-color 0.2s;
                user-select: none;
            }}
            
            .accordion-header:hover {{
                background-color: #f8f9fa;
            }}
            
            .accordion-header.active {{
                background-color: #f0f0f0;
            }}
            
            .accordion-title {{
                display: flex;
                align-items: center;
                gap: 12px;
                font-size: 18px;
                font-weight: 600;
                color: #2c3e50;
            }}
            
            .accordion-count {{
                background: #667eea;
                color: white;
                padding: 4px 12px;
                border-radius: 12px;
                font-size: 14px;
                font-weight: 600;
            }}
            
            .accordion-icon {{
                transition: transform 0.3s;
                font-size: 20px;
                color: #667eea;
            }}
            
            .accordion-header.active .accordion-icon {{
                transform: rotate(180deg);
            }}
            
            .accordion-content {{
                max-height: 0;
                overflow: hidden;
                transition: max-height 0.3s ease-out;
            }}
            
            .accordion-content.active {{
                max-height: 5000px;
                transition: max-height 0.5s ease-in;
            }}
            
            .accordion-body {{
                padding: 0 20px 20px 20px;
            }}
            
            .deal-card-wrapper {{
                margin-bottom: 12px;
            }}
            
            .deal-card {{
                background: white;
                padding: 20px;
                border-radius: 12px;
                box-shadow: 0 2px 8px rgba(0,0,0,0.05);
                transition: box-shadow 0.2s;
                display: flex;
                align-items: center;
                gap: 16px;
            }}
            
            .deal-card:hover {{
                box-shadow: 0 4px 16px rgba(0,0,0,0.1);
            }}
            
            .deal-payment {{
                flex-shrink: 0;
            }}
            
            .deal-card-link {{
                text-decoration: none;
                color: inherit;
                flex: 1;
                min-width: 0;
            }}
            
            .deal-content {{
                flex: 1;
                min-width: 0;
            }}
            
            .deal-payment-section {{
                display: flex;
                align-items: center;
                gap: 12px;
                flex-shrink: 0;
            }}
            
            .deal-amount {{
                font-size: 18px;
                font-weight: 700;
                color: #27ae60;
                white-space: nowrap;
            }}
            
            .payment-button {{
                padding: 6px 12px;
                background: #27ae60;
                color: white;
                border: none;
                border-radius: 6px;
                font-size: 12px;
                font-weight: 500;
                cursor: pointer;
                transition: background 0.2s;
                white-space: nowrap;
            }}
            
            .payment-button:hover {{
                background: #229954;
            }}
            
            .payment-button:active {{
                transform: scale(0.95);
            }}
            
            .payment-button:disabled {{
                background: #95a5a6;
                cursor: not-allowed;
            }}
            
            .payment-done {{
                padding: 6px 12px;
                background: #ecf0f1;
                color: #27ae60;
                border-radius: 6px;
                font-size: 12px;
                font-weight: 500;
                white-space: nowrap;
            }}
            
            .deal-header {{
                margin-bottom: 12px;
            }}
            
            .deal-title {{
                font-size: 16px;
                font-weight: 600;
                color: #2c3e50;
            }}
            
            .deal-meta {{
                display: flex;
                gap: 12px;
                align-items: center;
                flex-wrap: wrap;
            }}
            
            .deal-id {{
                font-size: 12px;
                color: #95a5a6;
            }}
            
            .deal-stage {{
                font-size: 12px;
                padding: 4px 12px;
                border-radius: 12px;
                font-weight: 500;
            }}
            
            .no-deals {{
                background: white;
                padding: 48px 24px;
                border-radius: 12px;
                text-align: center;
                box-shadow: 0 2px 8px rgba(0,0,0,0.05);
            }}
            
            .no-deals p:first-child {{
                font-size: 24px;
                margin-bottom: 12px;
            }}
            
            .no-deals .hint {{
                color: #7f8c8d;
                font-size: 14px;
            }}
        </style>
        <script>
            function toggleAccordion(element) {{
                const header = element;
                const content = header.nextElementSibling;
                const isActive = header.classList.contains('active');
                
                // Закрываем все другие accordion
                document.querySelectorAll('.accordion-header').forEach(h => {{
                    if (h !== header) {{
                        h.classList.remove('active');
                        h.nextElementSibling.classList.remove('active');
                    }}
                }});
                
                // Переключаем текущий accordion
                if (isActive) {{
                    header.classList.remove('active');
                    content.classList.remove('active');
                }} else {{
                    header.classList.add('active');
                    content.classList.add('active');
                }}
            }}
            
            async function markPaymentDone(event, dealId, dealAmount, partnerPercent) {{
                event.preventDefault();
                event.stopPropagation();
                
                const button = event.target;
                const originalText = button.textContent;
                button.disabled = true;
                button.textContent = '...';
                
                try {{
                    const response = await fetch('/api/mark-payment', {{
                        method: 'POST',
                        headers: {{
                            'Content-Type': 'application/json',
                        }},
                        body: JSON.stringify({{ deal_id: dealId }})
                    }});
                    
                    const result = await response.json();
                    if (response.ok && result.success) {{
                        // Заменяем кнопку на статус "Выплачено"
                        const paymentContainer = button.closest('.deal-payment');
                        paymentContainer.innerHTML = '<span class="payment-done">✓ Выплачено</span>';
                        
                        // Обновляем статистику "Выплачено" в шапке
                        updatePaidAmount(dealAmount, partnerPercent);
                    }} else {{
                        throw new Error(result.error || 'Ошибка обновления');
                    }}
                }} catch (error) {{
                    button.disabled = false;
                    button.textContent = originalText;
                    alert('Ошибка при обновлении статуса выплаты: ' + error.message);
                }}
            }}
            
            function updatePaidAmount(dealAmount, partnerPercent) {{
                // Находим элемент со статистикой "Выплачено"
                const paidStatItem = document.getElementById('paid-amount');
                
                if (paidStatItem) {{
                    // Получаем текущее значение
                    const currentText = paidStatItem.textContent.trim();
                    // Извлекаем число из текста (убираем валюту и пробелы, заменяем запятую на точку)
                    const cleaned = currentText.replace(/[^0-9.,]/g, '').replace(/,/g, '.');
                    const currentAmount = parseFloat(cleaned) || 0;
                    // Рассчитываем новую сумму (процент от суммы сделки)
                    const paymentAmount = dealAmount * (partnerPercent / 100);
                    const newAmount = currentAmount + paymentAmount;
                    // Определяем валюту из текущего текста
                    let currency = 'RUB';
                    if (currentText.includes('$') || currentText.includes('USD')) {{
                        currency = 'USD';
                    }} else if (currentText.includes('€') || currentText.includes('EUR')) {{
                        currency = 'EUR';
                    }}
                    // Форматируем и обновляем
                    const formatted = formatCurrency(newAmount, currency);
                    paidStatItem.textContent = formatted;
                }}
            }}
            
            function formatCurrency(amount, currency) {{
                const currencySymbols = {{
                    'RUB': '₽',
                    'USD': '$',
                    'EUR': '€'
                }};
                const symbol = currencySymbols[currency] || '₽';
                // Форматируем число с пробелами как разделителями тысяч
                const formatted = Math.round(amount).toLocaleString('ru-RU').replace(/,/g, ' ');
                return formatted + ' ' + symbol;
            }}
        </script>
    </head>
    <body>
        <div class="header">
            <h1>👋 {entity_info['name']}</h1>
            <p>Сделки и лиды в качестве партнера {entity_type}</p>
            <div class="header-stats">
                <div class="stat-item">
                    <div class="stat-label">Процент партнера</div>
                    <div class="stat-value">{partner_percent}%</div>
                </div>
                <div class="stat-item">
                    <div class="stat-label">Успешные сделки</div>
                    <div class="stat-value">{format_currency(success_amount, default_currency)}</div>
                </div>
                <div class="stat-item">
                    <div class="stat-label">В работе</div>
                    <div class="stat-value">{format_currency(in_progress_amount, default_currency)}</div>
                </div>
                <div class="stat-item">
                    <div class="stat-label">Выплачено</div>
                    <div class="stat-value" id="paid-amount">{format_currency(paid_amount, default_currency)}</div>
                </div>
            </div>
        </div>
        
        <div class="accordion">
            <div class="accordion-item">
                <div class="accordion-header" onclick="toggleAccordion(this)">
                    <div class="accordion-title">
                        <span>💼 Сделки</span>
                        <span class="accordion-count">{len(deals)}</span>
                    </div>
                    <span class="accordion-icon">▼</span>
                </div>
                <div class="accordion-content">
                    <div class="accordion-body">
                        {deals_html}
                    </div>
                </div>
            </div>
            
            <div class="accordion-item">
                <div class="accordion-header" onclick="toggleAccordion(this)">
                    <div class="accordion-title">
                        <span>🎯 Лиды</span>
                        <span class="accordion-count">{len(leads)}</span>
                    </div>
                    <span class="accordion-icon">▼</span>
                </div>
                <div class="accordion-content">
                    <div class="accordion-body">
                        {leads_html}
                    </div>
                </div>
            </div>
        </div>
    </body>
    </html>
    """
    
    return HTMLResponse(content=html_content)


@app.post("/api/mark-payment")
async def mark_payment(request: Request):
    """
    Endpoint для обновления статуса выплаты по сделке.
    Устанавливает поле PARTNER_IS_PAYMENT в true.
    """
    try:
        data = await request.json()
        deal_id = data.get("deal_id")
        
        if not deal_id:
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": "deal_id не указан"}
            )
        
        # Получаем webhook URL из переменных окружения
        webhook_url = os.getenv("WEBHOOK")
        
        if not webhook_url:
            logger.error("WEBHOOK не задан в .env")
            return JSONResponse(
                status_code=500,
                content={"success": False, "error": "WEBHOOK не настроен"}
            )
        
        # Создаем клиент Битрикс24
        bitrix = BitrixAsync(webhook_url)
        
        # Обновляем поле PARTNER_IS_PAYMENT
        # Поле принимает значения "0" или "1"
        result = await bitrix.call("crm.deal.update", {
            "ID": deal_id,
            "fields": {
                PARTNER_IS_PAYMENT_FIELD: "1"
            }
        })
        
        if result and "error" not in str(result):
            logger.info(f"Выплата отмечена для сделки #{deal_id}")
            return JSONResponse(
                status_code=200,
                content={"success": True, "deal_id": deal_id}
            )
        else:
            logger.error(f"Ошибка обновления сделки #{deal_id}: {result}")
            return JSONResponse(
                status_code=500,
                content={"success": False, "error": "Ошибка обновления сделки"}
            )
            
    except Exception as e:
        logger.error(f"Ошибка при обновлении выплаты: {e}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )


@app.get("/", response_class=HTMLResponse)
async def root():
    """Корневой endpoint для проверки работы сервиса."""
    return HTMLResponse(content="""
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Битрикс24 Webhook Handler</title>
        <style>
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                display: flex;
                align-items: center;
                justify-content: center;
                min-height: 100vh;
                margin: 0;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            }
            .container {
                background: white;
                padding: 40px;
                border-radius: 16px;
                box-shadow: 0 10px 40px rgba(0,0,0,0.2);
                text-align: center;
            }
            h1 {
                color: #2c3e50;
                margin-bottom: 20px;
            }
            p {
                color: #7f8c8d;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>✅ Битрикс24 Webhook Handler</h1>
            <p>Сервис работает корректно</p>
            <p>Используйте POST /webhook для обработки webhook от Битрикс24</p>
        </div>
    </body>
    </html>
    """)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
    # import asyncio
    # asyncio.run(get_deal_stages("0", BitrixAsync(os.getenv("WEBHOOK"))))