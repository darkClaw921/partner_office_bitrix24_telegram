# UTM Partner Binding Service

Сервис автоматической привязки партнеров к сделкам и лидам в Bitrix24 на основе UTM метки `utm_term`.

## Функционал

- Принимает webhook от Bitrix24 при создании/изменении документа сделки или лида
- Извлекает UTM метку `utm_term` из сделки/лида
- Ищет партнера по коду из UTM метки (сначала в контактах, затем в компаниях)
- Автоматически привязывает партнера к сделке или лиду

## Установка

```bash
cd utm_partner_binding
uv sync
```

## Настройка

Скопируйте `.env` файл и заполните необходимые переменные:

- `WEBHOOK` - webhook URL Bitrix24 (опционально, может браться из хука)
- `PARTNER_CONTACT_CODE_FIELD` - поле кода партнера в контактах
- `PARTNER_COMPANY_CODE_FIELD` - поле кода партнера в компаниях
- `PARTNER_DEAL_REF_DEAL` - поле привязки партнера в сделках
- `PARTNER_LEAD_REF_LEAD` - поле привязки партнера в лидах

## Запуск

```bash
uv run main.py
```

Сервер будет доступен на `http://localhost:8000`

## Endpoints

- `GET /` - проверка работы сервиса
- `POST /webhook` - обработчик webhook от Bitrix24

## Формат хука от Bitrix24

```python
{
    'auth[client_endpoint]': 'https://test-rosdomofon.bitrix24.ru/rest/',
    'auth[domain]': 'test-rosdomofon.bitrix24.ru',
    'auth[member_id]': 'c136a48eb8acd7f36bf88927b9000083',
    'auth[server_endpoint]': 'https://oauth.bitrix24.tech/rest/',
    'document_id[0]': 'crm',
    'document_id[1]': 'CCrmDocumentDeal',  # или 'CCrmDocumentLead'
    'document_id[2]': 'DEAL_1'  # или 'LEAD_1'
}
```

## Ответ

Сервис возвращает JSON ответ с результатом обработки:

```json
{
    "success": true,
    "message": "Партнер успешно привязан к сделке",
    "entity_type": "deal",
    "entity_id": "1",
    "partner_type": "contact",
    "partner_id": "123"
}
```

