import json
import os
from urllib.parse import parse_qs
from typing import Dict

from dotenv import load_dotenv
from fast_bitrix24 import BitrixAsync
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from loguru import logger

# Загружаем переменные окружения
load_dotenv()

app = FastAPI()

# Получаем название поля из переменных окружения
PARTNER_DEAL_REF_FIELD = os.getenv("PARTNER_DEAL_REF_DEAL", "UF_CRM_1763470519")

domain=os.getenv("WEBHOOK").split("/")[2]

# Кэш для статусов воронок
_stage_cache: Dict[str, Dict[str, str]] = {}
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
                
                return {
                    "id": contact_id,
                    "name": " ".join(name_parts) or f"Контакт #{contact_id}"
                }
        
        return {"id": contact_id, "name": f"Контакт #{contact_id}"}
                
    except Exception as e:
        logger.error(f"Ошибка получения данных контакта #{contact_id}: {e}")
        return {"id": contact_id, "name": f"Контакт #{contact_id}"}


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
                return {
                    "id": company_id,
                    "name": company_data.get("TITLE", f"Компания #{company_id}")
                }
        
        return {"id": company_id, "name": f"Компания #{company_id}"}
                
    except Exception as e:
        logger.error(f"Ошибка получения данных компании #{company_id}: {e}")
        return {"id": company_id, "name": f"Компания #{company_id}"}


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
                    "CONTACT_ID"
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
                    "CONTACT_ID"
                ]
            }
        )
        
        logger.info(f"Найдено сделок: {len(deals) if deals else 0}")
        
        return deals if deals else []
                
    except Exception as e:
        logger.error(f"Ошибка получения сделок для компании #{company_id}: {e}")
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
        'AUTH_ID': '3887b068007b96ee007b49e800000001000007c425c8345a9600bd3f00fed57371e60d',
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
        # Получаем все сделки контакта
        deals = await get_contact_deals(entity_id, bitrix, domain)
        entity_type = "контакта"
    elif placement == 'CRM_COMPANY_DETAIL_TAB':
        entity_info = await get_company_info(entity_id, bitrix)
        # Получаем все сделки компании
        deals = await get_company_deals(entity_id, bitrix, domain)
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
            
            # Получаем название стадии
            stage_name = stages_map.get(category_id, {}).get(stage_id, stage_id)

            # Формируем ссылку на сделку
            deal_url = f"https://{domain}/crm/deal/details/{deal_id}/" if member_id else "#"
            
            # Определяем цвет стадии
            stage_color = "#3498db"  # По умолчанию синий
            if "WON" in stage_id.upper() or "SUCCESS" in stage_id.upper():
                stage_color = "#2ecc71"  # Зеленый для выигранных
            elif "LOSE" in stage_id.upper() or "FAIL" in stage_id.upper():
                stage_color = "#e74c3c"  # Красный для проигранных
            
            deals_html += f"""
            <a href="{deal_url}" class="deal-card-link" target="_blank">
                <div class="deal-card">
                    <div class="deal-header">
                        <div class="deal-title">{title}</div>
                        <div class="deal-amount">{format_currency(amount, currency)}</div>
                    </div>
                    <div class="deal-meta">
                        <span class="deal-id">ID: {deal_id}</span>
                    <span class="deal-stage" style="background-color: {stage_color}20; color: {stage_color};">
                        {stage_name}
                    </span>
                    </div>
                </div>
            </a>
            """
    else:
        deals_html = """
        <div class="no-deals">
            <p>📋 Сделок не найдено</p>
            <p class="hint">У этой сущности пока нет сделок в качестве партнера</p>
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
            
            .deals-count {{
                background: white;
                padding: 16px 20px;
                border-radius: 8px;
                margin-bottom: 16px;
                display: flex;
                justify-content: space-between;
                align-items: center;
                box-shadow: 0 2px 8px rgba(0,0,0,0.05);
            }}
            
            .deals-count-label {{
                color: #7f8c8d;
                font-size: 14px;
            }}
            
            .deals-count-value {{
                font-size: 24px;
                font-weight: 700;
                color: #667eea;
            }}
            
            .deal-card-link {{
                text-decoration: none;
                color: inherit;
                display: block;
            }}
            
            .deal-card {{
                background: white;
                padding: 20px;
                border-radius: 12px;
                margin-bottom: 12px;
                box-shadow: 0 2px 8px rgba(0,0,0,0.05);
                transition: transform 0.2s, box-shadow 0.2s;
                cursor: pointer;
            }}
            
            .deal-card-link:hover .deal-card {{
                transform: translateY(-2px);
                box-shadow: 0 4px 16px rgba(0,0,0,0.1);
            }}
            
            .deal-header {{
                display: flex;
                justify-content: space-between;
                align-items: start;
                margin-bottom: 12px;
            }}
            
            .deal-title {{
                font-size: 16px;
                font-weight: 600;
                color: #2c3e50;
                flex: 1;
                margin-right: 16px;
            }}
            
            .deal-amount {{
                font-size: 18px;
                font-weight: 700;
                color: #27ae60;
                white-space: nowrap;
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
    </head>
    <body>
        <div class="header">
            <h1>👋 {entity_info['name']}</h1>
            <p>Сделки в качестве партнера {entity_type}</p>
        </div>
        
        <div class="deals-count">
            <span class="deals-count-label">Всего сделок:</span>
            <span class="deals-count-value">{len(deals)}</span>
        </div>
        
        {deals_html}
    </body>
    </html>
    """
    
    return HTMLResponse(content=html_content)


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