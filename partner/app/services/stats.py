from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

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


STAGE_SUCCESS = {"WON", "SUCCESS"}
STAGE_FAILED = {"LOSE", "FAILED"}


async def fetch_deal_stats(
    partner_contact_id: int,
    range_key: StatsRange,
    service: BitrixService | None = None,
) -> DealStats:
    client = service or get_bitrix_service()
    date_from = _resolve_date_from(range_key)
    settings = get_settings()

    filter_payload: dict[str, object] = {settings.partner_deal_ref_field: partner_contact_id}
    if date_from:
        filter_payload[">=DATE_CREATE"] = date_from.isoformat()

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

