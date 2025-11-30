from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from logging import Logger
from typing import Literal

from loguru import logger

from app.config import get_settings
from app.utils.workBitrix24 import BitrixService, get_bitrix_service

StatsRange = Literal["today", "week", "all"]


@dataclass(slots=True)
class DealStats:
    in_progress: int
    success: int
    failed: int
    in_progress_amount: float
    success_amount: float
    failed_amount: float
    total_amount: float

    @classmethod
    def empty(cls) -> DealStats:
        return cls(0, 0, 0, 0.0, 0.0, 0.0, 0.0)


@dataclass(slots=True)
class ClientDealInfo:
    client_id: int
    client_name: str
    client_type: str  # "contact" or "company"
    deals_count: int
    deals_in_progress: int
    deals_success: int
    deals_failed: int
    in_progress_amount: float
    success_amount: float
    failed_amount: float
    total_amount: float
    stages: dict[str, int]  # stage_name -> count


@dataclass(slots=True)
class DetailedStats:
    clients: list[ClientDealInfo]
    stage_names: dict[str, str]  # stage_id -> stage_name


STAGE_SUCCESS = {"WON", "SUCCESS"}
STAGE_FAILED = {"LOSE", "FAILED"}


async def _get_partner_binding(partner_id: int, service: BitrixService, entity_type: str | None = None) -> str:
    """
    Определение формата привязки партнера в зависимости от типа (контакт или компания).
    Возвращает строку в формате "C_<id>" для контакта или "CO_<id>" для компании.
    If entity_type is provided, use it instead of making API calls.
    """
    # If we already know the entity type, use it
    if entity_type == "C_":
        return f"C_{partner_id}"
    elif entity_type == "CO_":
        return f"CO_{partner_id}"
    elif entity_type is not None:
        # For backward compatibility, if entity_type is something else but not None
        return f"{entity_type}{partner_id}"
    
    # Otherwise, determine by making API calls (backward compatibility)
    # Проверяем, является ли partner_id контактом
    contact_result = await service.call("crm.contact.get", {"id": partner_id})
    if contact_result and isinstance(contact_result, dict) and "error" not in contact_result:
        # Это контакт
        return f"C_{partner_id}"
    
    # Проверяем, является ли partner_id компанией
    company_result = await service.call("crm.company.get", {"id": partner_id})
    if company_result and isinstance(company_result, dict) and "error" not in company_result:
        # Это компания
        return f"CO_{partner_id}"
    
    # По умолчанию считаем контактом (обратная совместимость)
    return f"C_{partner_id}"


async def fetch_deal_stats(
    partner_id: int,
    range_key: StatsRange,
    service: BitrixService | None = None,
    entity_type: str | None = None  # Added entity_type parameter
) -> DealStats:
    client = service or get_bitrix_service()
    date_from = _resolve_date_from(range_key)
    settings = get_settings()
    
    # Определяем формат привязки партнера
    partner_binding = await _get_partner_binding(partner_id, client, entity_type)

    filter_payload: dict[str, object] = {settings.partner_deal_ref_field: partner_binding}
    if date_from:
        filter_payload[">=DATE_CREATE"] = date_from.isoformat()
    print(filter_payload)
    deals = await client.get_all("crm.deal.list", params={"filter": filter_payload, "select": ["STAGE_ID", "OPPORTUNITY"]})
    stats = DealStats.empty()
    for deal in deals:
        stage = str(deal.get("STAGE_ID", "")).upper()
        amount = float(deal.get("OPPORTUNITY") or 0)
        if any(tag in stage for tag in STAGE_SUCCESS):
            stats.success += 1
            stats.success_amount += amount
        elif any(tag in stage for tag in STAGE_FAILED):
            stats.failed += 1
            stats.failed_amount += amount
        else:
            stats.in_progress += 1
            stats.in_progress_amount += amount
        stats.total_amount += amount
    return stats


def _resolve_date_from(range_key: StatsRange) -> datetime | None:
    now = datetime.now(timezone.utc)
    if range_key == "today":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if range_key == "week":
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return start_of_day - timedelta(days=7)
    return None


async def _get_stage_names(service: BitrixService, category_id: int | None = None) -> dict[str, str]:
    """
    Получает названия стадий сделок из Bitrix24.
    Если category_id не указан, получает стадии из всех воронок.
    """
    stage_names: dict[str, str] = {}
    
    try:
        # Получаем список воронок для сделок (entityTypeId=2 для сделок)
        categories_response = await service.call("crm.category.list", {"entityTypeId": 2})
        print(categories_response)
        if not categories_response:
            logger.warning("Не удалось получить список воронок сделок: пустой ответ")
            return stage_names
        
        # Обрабатываем ответ API (может быть dict с result или list)
        if isinstance(categories_response, dict):
            if "error" in categories_response:
                logger.warning(f"Ошибка при получении воронок: {categories_response.get('error')}")
                return stage_names
            categories = categories_response.get("result", [])
        else:
            categories = categories_response
        
        if not isinstance(categories, list):
            logger.warning("Неожиданный формат ответа от crm.category.list")
            return stage_names
        
        # Если указана конкретная категория, получаем только её
        if category_id:
            categories_list = [cat for cat in categories if cat.get("id") == category_id]
        else:
            categories_list = categories
        
        # Получаем стадии из каждой воронки
        for category in categories_list:
            cat_id = category.get("id")
            if not cat_id:
                continue
                
            try:
                category_info = await service.call("crm.category.get", {
                    "entityTypeId": 2,
                    "id": cat_id
                })
                
                if not category_info:
                    continue
                
                # Обрабатываем ответ API
                if isinstance(category_info, dict):
                    if "error" in category_info:
                        logger.warning(f"Ошибка при получении воронки {cat_id}: {category_info.get('error')}")
                        continue
                    category_data = category_info.get("result", category_info)
                else:
                    category_data = category_info
                
                if not isinstance(category_data, dict):
                    continue
                
                stages = category_data.get("stages", [])
                if not isinstance(stages, list):
                    continue
                
                for stage in stages:
                    if not isinstance(stage, dict):
                        continue
                    stage_id = stage.get("statusId")
                    stage_name = stage.get("name")
                    if stage_id and stage_name:
                        # Сохраняем как обычный ID
                        stage_names[str(stage_id)] = str(stage_name)
                        # Также сохраняем как составной ID если у нас есть category_id
                        if cat_id:
                            composite_id = f"{cat_id}:{stage_id}"
                            stage_names[composite_id] = str(stage_name)
            except Exception as e:
                logger.warning(f"Ошибка при получении стадий воронки {cat_id}: {e}")
                continue
                
    except Exception as e:
        logger.error(f"Ошибка при получении стадий сделок: {e}")
    
    return stage_names


async def fetch_detailed_stats(
    partner_id: int,
    range_key: StatsRange,
    service: BitrixService | None = None,
    entity_type: str | None = None
) -> DetailedStats:
    """
    Получает детальную статистику по клиентам и стадиям сделок.
    """
    client = service or get_bitrix_service()
    date_from = _resolve_date_from(range_key)
    settings = get_settings()
    
    # Определяем формат привязки партнера
    partner_binding = await _get_partner_binding(partner_id, client, entity_type)
    
    filter_payload: dict[str, object] = {settings.partner_deal_ref_field: partner_binding}
    if date_from:
        filter_payload[">=DATE_CREATE"] = date_from.isoformat()
    
    # Получаем сделки с информацией о клиентах и стадиях
    deals = await client.get_all(
        "crm.deal.list",
        params={
            "filter": filter_payload,
            "select": [
                "STAGE_ID",
                "OPPORTUNITY",
                "COMPANY_ID",
                "CONTACT_ID",
                "CATEGORY_ID"
            ]
        }
    )
    
    # Получаем названия стадий
    stage_names: dict[str, str] = {}
    category_ids = set()
    for deal in deals:
        cat_id = deal.get("CATEGORY_ID")
        if cat_id:
            category_ids.add(int(cat_id))
    
    # Получаем стадии из всех найденных воронок
    for cat_id in category_ids:
        stages = await _get_stage_names(client, cat_id)
        stage_names.update(stages)
    
    # Если не удалось получить стадии, получаем из всех воронок
    if not stage_names:
        stage_names = await _get_stage_names(client)
    
    # Улучшенная обработка стадий: добавляем стандартные стадии как резерв
    standard_stages = {
        "NEW": "Новая",
        "WON": "Выиграна",
        "LOSE": "Проиграна"
    }
    
    # Объединяем полученные стадии со стандартными
    for stage_id, stage_name in standard_stages.items():
        if stage_id not in stage_names:
            stage_names[stage_id] = stage_name
    
    # Группируем сделки по клиентам
    clients_data: dict[tuple[int, str], dict] = defaultdict(lambda: {
        "deals_count": 0,
        "deals_in_progress": 0,
        "deals_success": 0,
        "deals_failed": 0,
        "in_progress_amount": 0.0,
        "success_amount": 0.0,
        "failed_amount": 0.0,
        "total_amount": 0.0,
        "stages": defaultdict(int)
    })
    
    client_names: dict[tuple[int, str], str] = {}
    
    for deal in deals:
        company_id = deal.get("COMPANY_ID")
        contact_id = deal.get("CONTACT_ID")
        stage_id = str(deal.get("STAGE_ID", ""))
        amount = float(deal.get("OPPORTUNITY") or 0)
        
        # Определяем клиента (приоритет компании)
        if company_id:
            client_key = (int(company_id), "company")
            if client_key not in client_names:
                try:
                    company = await client.call("crm.company.get", {"id": company_id})
                    company=company.get('order0000000000')
                    if company and isinstance(company, dict) and "error" not in company:
                        client_names[client_key] = company.get("TITLE", f"Компания {company_id}")
                except Exception:
                    client_names[client_key] = f"Компания {company_id}"
        elif contact_id:
            client_key = (int(contact_id), "contact")
            # print(contact_id)
            if client_key not in client_names:
                try:
                    contact = await client.call("crm.contact.get", {"id": contact_id})
                    contact=contact.get('order0000000000')
                    # print(contact)
                    # print('================')
                    if contact and isinstance(contact, dict) and "error" not in contact:
                        name_parts = ["Клиент"]
                        if contact.get("NAME"):
                            name_parts.append(contact.get("NAME"))
                        if contact.get("LAST_NAME"):
                            name_parts.append(contact.get("LAST_NAME"))
                        client_names[client_key] = " ".join(name_parts) or contact.get("SECOND_NAME") or f"Клиент {contact_id}"
                except Exception:
                    client_names[client_key] = f"Клиент {contact_id}"
        else:
            # Сделка без клиента
            client_key = (0, "unknown")
            if client_key not in client_names:
                client_names[client_key] = "Без клиента"
        
        # Обновляем статистику по клиенту
        client_data = clients_data[client_key]
        client_data["deals_count"] += 1
        
        # Определяем статус сделки
        stage_upper = stage_id.upper()
        if any(tag in stage_upper for tag in STAGE_SUCCESS):
            client_data["deals_success"] += 1
            client_data["success_amount"] += amount
        elif any(tag in stage_upper for tag in STAGE_FAILED):
            client_data["deals_failed"] += 1
            client_data["failed_amount"] += amount
        else:
            client_data["deals_in_progress"] += 1
            client_data["in_progress_amount"] += amount
            
        client_data["total_amount"] += amount
        
        # Получаем название стадии
        stage_name = stage_names.get(stage_id, stage_id)
        client_data["stages"][stage_name] += 1
    
    # Формируем список клиентов
    clients_list: list[ClientDealInfo] = []
    for (client_id, client_type), data in clients_data.items():
        clients_list.append(ClientDealInfo(
            client_id=client_id,
            client_name=client_names.get((client_id, client_type), f"Клиент {client_id}"),
            client_type=client_type,
            deals_count=data["deals_count"],
            deals_in_progress=data["deals_in_progress"],
            deals_success=data["deals_success"],
            deals_failed=data["deals_failed"],
            in_progress_amount=data["in_progress_amount"],
            success_amount=data["success_amount"],
            failed_amount=data["failed_amount"],
            total_amount=data["total_amount"],
            stages=dict(data["stages"])
        ))
    
    # Сортируем по количеству сделок (по убыванию)
    clients_list.sort(key=lambda x: x.deals_count, reverse=True)
    
    return DetailedStats(
        clients=clients_list,
        stage_names=stage_names
    )