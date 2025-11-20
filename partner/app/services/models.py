from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class PartnerSubmission:
    user_id: int
    username: str | None
    first_name: str | None
    last_name: str | None
    phone_number: str
    partner_code: str
    bitrix_contact_id: int | None = None
    bitrix_entity_type: str | None = None  # Added to store whether it's a contact (C_) or company (CO_)
    created_at: datetime | None = None