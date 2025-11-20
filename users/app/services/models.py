from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass(slots=True)
class UserRequest:
    user_id: int
    partner_code: str
    name: Optional[str] = None
    phone: Optional[str] = None
    bitrix_deal_id: Optional[str] = None
    created_at: Optional[datetime] = None