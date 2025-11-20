from __future__ import annotations


def normalize_phone(phone: str) -> str:
    """Нормализация телефонного номера в формат +79308312222
    
    Поддерживаемые форматы:
    - +79308312222
    - 89308312222
    - 79308312222
    - +7 930 831 22 22
    - 8 (930) 831-22-22
    - и любые другие варианты с пробелами, скобками, дефисами
    """
    phone=str(phone)
    # Удаляем все нецифровые символы кроме +
    cleaned = ''.join(c for c in phone if c.isdigit() or c == '+')
    
    # Удаляем + если есть
    cleaned = cleaned.lstrip('+')
    
    # Обрабатываем российские номера
    if cleaned.startswith('8') and len(cleaned) == 11:
        # 8XXXXXXXXXX -> 7XXXXXXXXXX
        cleaned = '7' + cleaned[1:]
    elif cleaned.startswith('7') and len(cleaned) == 11:
        # Уже в нужном формате
        pass
    elif len(cleaned) == 10:
        # XXXXXXXXXX -> 7XXXXXXXXXX
        cleaned = '7' + cleaned
    else:
        # Пытаемся взять последние 10 цифр и добавить 7
        if len(cleaned) > 10:
            cleaned = '7' + cleaned[-10:]
    
    # Добавляем префикс +
    return cleaned
    
def format_phone_variants(phone: str) -> list[str]:
    """Генерация всех популярных форматов телефонного номера
    
    Args:
        phone: телефон в любом формате
    
    Returns:
        list[str] со всеми вариантами форматирования:
        - international: +79308312222
        - local_8: 89308312222
        - local_7: 79308312222
        - digits_only: 9308312222
        - formatted_plus: +7 930 831 22 22
        - formatted_8: 8 (930) 831-22-22
        - formatted_7: 7 (930) 831-22-22
        - formatted_brackets: (930) 831-22-22
    """
    # Сначала нормализуем номер
    normalized = normalize_phone(phone)
    
    # Извлекаем части номера: 79308312222
    if len(normalized) == 11:
        country = normalized[0]  # 7
        code = normalized[1:4]   # 930
        part1 = normalized[4:7]  # 831
        part2 = normalized[7:9]  # 22
        part3 = normalized[9:11] # 22
        digits_only = normalized[1:]  # 9308312222
    else:
        # Если формат нестандартный, возвращаем минимум
        return [
            f"+{normalized}",
            normalized
        ]
    
    return [
        f"+{normalized}",
        f"8{digits_only}",
        str(normalized),
        digits_only,
        f"+{country} {code} {part1} {part2} {part3}",
        f"8 ({code}) {part1}-{part2}-{part3}",
        f"{country} ({code}) {part1}-{part2}-{part3}",
        f"({code}) {part1}-{part2}-{part3}",
        f"+{country}-{code}-{part1}-{part2}-{part3}",
        f"8-{code}-{part1}-{part2}-{part3}",
    ]