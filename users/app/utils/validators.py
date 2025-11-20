from __future__ import annotations

import re


PHONE_PATTERN = re.compile(r"\d+")
NAME_PATTERN = re.compile(r"^[a-zA-Zа-яА-ЯёЁ\s]{2,50}$")


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


def is_valid_name(value: str) -> bool:
    return bool(NAME_PATTERN.match(value.strip()))