## Описание
Телеграм-бот на `aiogram 3` для пользователей, пришедших от партнера. Поддерживает deep linking: /start <код_партнера> или t.me/bot?start=param (где param - код партнера, включая UTM-метки типа cqi_utm_source=google-cqi_utm_medium=cpc-cqi_utm_campaign=summer). Собирает код партнера, предоставляет документы (текст/файл из JSON), позволяет записаться на консультацию (согласие на данные, имя, телефон с валидацией), создает сделку в Bitrix24 с привязкой к партнеру по коду (crm.deal.add с UF_CRM_PARTNER_CODE). Данные в SQLite, логи в loguru.

## Требования
- Python 3.12+
- Установленный `pip`/`uv`
- Токен Telegram-бота от [@BotFather](https://t.me/BotFather)

## Установка
```bash
cd users
python -m venv .venv
source .venv/bin/activate  # или .venv\Scripts\activate на Windows
pip install -e .
```

## Настройка окружения
1. Скопируйте `.env.example` в `.env`.
2. Заполните `BOT_TOKEN` (токен бота).
3. Укажите `DATABASE_PATH` (путь к SQLite, по умолчанию database.sqlite).
4. `LOG_LEVEL` (INFO по умолчанию).
5. `WEBHOOK` (Bitrix24 REST API: https://<domain>.bitrix24.ru/rest/<user_id>/<webhook_token>).
6. Опционально `DOCUMENTS_PATH` (путь к documents.json, по умолчанию app/config/documents.json).
7. Настройте документы в `documents.json`: массив объектов {id, title, type: "text"/"file", content/path}. Для файлов укажите относительный путь (бот отправит FSInputFile).

## Запуск бота
```bash
python main.py
```

При старте бот:
- Инициализирует SQLite и создаёт таблицу `user_requests` (user_id UNIQUE, partner_code, name, phone, bitrix_deal_id, created_at).
- Обрабатывает `/start <код>`: сохраняет код партнера в БД, проверяет дубли (если есть - показывает меню), отображает клавиатуру (Документы, Консультация).
- "Документы": inline-меню, отправка текста или файла (aiofiles не требуется, aiogram использует FSInputFile).
- "Консультация": FSM - согласие (inline Yes/No), ввод имени (валидация 2-50 символов), телефона (10-15 цифр, нормализация +7...), создание сделки в Bitrix (TITLE="Консультация: имя", PHONE, UF_CRM_PARTNER_CODE=код, SOURCE_ID=TELEGRAM_BOT, STAGE_ID=NEW), сохранение deal_id в БД.
- `/cancel`: сбрасывает FSM, возвращает меню.
- Логи в stdout и logs/bot.log (ротация 10MB, retention 7 дней).

## Структура
Подробности в `architecture.md`. Ключевые элементы:
- `app/config.py` — загрузка .env, documents.json.
- `app/bot/handlers.py` — FSM: start с парсингом аргумента (поддержка deep link ?start=param), документы (callback doc:id), консультация (consent, name, phone), интеграция с БД/Bitrix.
- `app/bot/keyboards.py` — main_keyboard (reply), documents_keyboard (inline из JSON), consent_keyboard.
- `app/db/database.py` — Database с save_request/get_request_by_user.
- `app/services/models.py` — UserRequest dataclass.
- `app/utils/validators.py` — is_valid_name/phone, normalize_phone.
- `app/utils/workBitrix24.py` — BitrixService с create_deal (crm.deal.add).

## Тестирование
- Deep link: t.me/bot?start=testcode - код сохранится как "testcode".
- UTM: ?start=cqi_utm_source=google... - весь параметр как код партнера.
- Документы: настройте JSON, добавьте файлы в app/config/docs/ (или укажите путь).
- Bitrix: протестируйте webhook, поле UF_CRM_PARTNER_CODE (адаптируйте если нужно).
- БД: проверьте таблицу после /start и консультации.

Для обновлений architecture.md смотрите инструкции в файле.