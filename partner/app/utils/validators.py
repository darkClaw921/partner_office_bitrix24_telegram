from __future__ import annotations

import re

PHONE_PATTERN = re.compile(r"\d+")
PARTNER_CODE_PATTERN = re.compile(r"^[A-Z0-9_-]{3,32}$")


def normalize_phone(raw_value: str) -> str:
    digits = "".join(PHONE_PATTERN.findall(raw_value))
    if digits.startswith("8") and len(digits) == 11:
        digits = f"7{digits[1:]}"
    if digits and not digits.startswith("+"):
        digits = f"+{digits}"
    return digits


def is_valid_phone(raw_value: str) -> bool:
    digits = "".join(PHONE_PATTERN.findall(raw_value))
    return 10 <= len(digits) <= 15


def normalize_partner_code(value: str) -> str:
    return value.strip().upper().replace(" ", "_")


def is_valid_partner_code(value: str) -> bool:
    normalized = normalize_partner_code(value)
    return bool(normalized and PARTNER_CODE_PATTERN.match(normalized))

