# Архитектура проекта

## Общее описание
Бот построен на `aiogram 3` и работает поверх `asyncio`. Состояние диалога управляется через FSM, данные сохраняются в SQLite через `aiosqlite`, конфигурация загружается из `.env`, логирование выполнено через `loguru`. Документы настраиваются в JSON, интеграция с Bitrix24 для создания лидов с привязкой к партнеру по коду.

## Структура
- `main.py` — точка входа. Загружает настройки, инициализирует логирование, базу данных, бота и диспетчер, запускает polling.
- `pyproject.toml` — управление зависимостями и метаданными проекта.
- `.env.example` — образец переменных окружения (`BOT_TOKEN`, `DATABASE_PATH`, `LOG_LEVEL`, `WEBHOOK`).
- `README.md` — инструкции по настройке и запуску.
- `logs/` — создаётся автоматически для хранения файлов логов (`bot.log`).
- `database.sqlite` — SQLite-файл БД.

### Пакет `app`
- `app/__init__.py` — метаданные пакета.
- `app/config.py` — загрузка настроек из окружения, подготовка пути к базе, загрузка `documents.json`.
- `app/logger.py` — конфигурация `loguru` (stdout + ротация файлов).

#### `app/bot`
- `app/bot/__init__.py` — фабрики `Bot` и `Dispatcher`, подключение роутеров и middleware.
- `app/bot/handlers.py` — FSM-сценарий: `/start <код_партнера>` (сохранение кода, проверка существования), кнопки "Документы" (inline-меню с проверкой настройки документов, отправка текста/файла), "Консультация" (согласие, имя, телефон, создание лида в Bitrix), обработка `/cancel`; callback-обработчики для inline-действий (action:documents с проверкой документов, action:consultation для запуска консультации); fallback-хэндлер для инициализации state из БД для существующих пользователей (если state None, загрузка partner_code из БД и установка waiting_start).

#### `app/db`
- `app/db/database.py` — класс `Database` с инициализацией схемы (таблица `user_requests`: user_id UNIQUE, partner_code, name, phone, bitrix_deal_id, created_at), методами `save_request`, `get_request_by_user`. 
  *Примечание: поле bitrix_deal_id используется для хранения идентификатора лида для обратной совместимости.*

#### `app/middlewares`
- `app/middlewares/database.py` — middleware, пробрасывающее экземпляр `Database` в хэндлеры.

#### `app/services`
- `app/services/models.py` — dataclass `UserRequest` (user_id, partner_code, name, phone, bitrix_deal_id, created_at).

#### `app/utils`
- `app/utils/validators.py` — нормализация и проверка телефона (`normalize_phone`, `is_valid_phone`), имени (`is_valid_name`).
- `app/utils/workBitrix24.py` — асинхронный клиент Bitrix24 (`BitrixService` с `find_partner_by_code`: поиск контакта партнера по коду; `create_lead`: создание лида с именем и телефоном клиента, привязка к партнеру через пользовательское поле PARTNER_LEAD_REF_LEAD типа "привязка к нескольким элементам CRM", crm.lead.add с TITLE, NAME, SOURCE_ID=TELEGRAM_BOT, STATUS_ID=NEW, правильная обработка ответа: int > 0 или dict['result'] как ID успеха). Контакты клиентов больше не создаются, номер телефона сохраняется в лид.