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
    created_at: datetime | None = None

