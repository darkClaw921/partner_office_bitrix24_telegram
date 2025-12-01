# Bitrix24 Webhook Handler

Обработчик webhook от Битрикс24 для встраивания в элемент сделки.

## Функционал

- Принимает webhook от Битрикс24 (поддержка JSON, form-urlencoded)
- Парсит `PLACEMENT_OPTIONS` для получения ID сделки
- Получает название сделки через API Битрикс24
- Возвращает HTML страницу с приветствием и названием сделки

## Установка

```bash
cd detail_deal_for_partner
uv sync
```

## Запуск

```bash
uv run main.py
```

Сервер будет доступен на `http://localhost:8000`

## Endpoints

- `GET /` - проверка работы сервиса
- `POST /webhook` - обработчик webhook от Битрикс24

## Пример запроса от Битрикс24

```python
{
    'AUTH_EXPIRES': '3600',
    'AUTH_ID': '3887b068007b96ee007b49e800000001000007c425c8345a9600bd3f00fed57371e60d',
    'PLACEMENT': 'CRM_DEAL_DETAIL_ACTIVITY',
    'PLACEMENT_OPTIONS': '{"ID":"1"}',
    'REFRESH_ID': '2806d868007b96ee007b49e800000001000007224ba3bff481836412123c08db5986e9',
    'member_id': '48620745570fb488aebad2cc4f4b9072',
    'status': 'L'
}
```

## Ответ

HTML страница с приветствием "Hello" и названием сделки.
