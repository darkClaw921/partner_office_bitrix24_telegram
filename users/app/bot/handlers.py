from __future__ import annotations

from aiogram import F, Router, types
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, FSInputFile, Message
from pathlib import Path
from loguru import logger

from app.bot.keyboards import consent_keyboard, documents_keyboard, hide_keyboard, main_keyboard, inline_main_keyboard
from app.config import get_settings
from app.db.database import Database
from app.utils.validators import is_valid_name, is_valid_phone, normalize_phone
from app.utils.workBitrix24 import BitrixNotConfiguredError, create_lead  # Changed from create_deal


router = Router(name="user_bot")


class UserForm(StatesGroup):
    waiting_start = State()
    documents = State()
    consultation_consent = State()
    consultation_name = State()
    consultation_phone = State()


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext, db: Database) -> None:
    user = message.from_user
    if not user:
        await message.answer("Ошибка: не удалось определить пользователя.")
        return

    # Парсинг кода партнера из аргумента /start code123
    args = message.text.split(maxsplit=1)
    partner_code = args[1].strip() if len(args) > 1 else None

    if not partner_code:
        await message.answer("Используйте /start <код_партнера> для начала работы.")
        return

    # Проверка существования пользователя
    existing_request = await db.get_request_by_user(user.id)
    if existing_request:
        partner_code = existing_request['partner_code']  # Использовать код из БД как dict
        await message.answer(
            "Вы уже зарегистрированы. Используйте кнопки ниже для действий.",
            reply_markup=main_keyboard,
        )
        await state.set_state(UserForm.waiting_start)
        await state.update_data(partner_code=partner_code)
        return

    # Сохранение кода партнера
    await state.set_state(UserForm.waiting_start)
    await state.update_data(partner_code=partner_code)
    await db.save_request(user.id, partner_code)

    await message.answer(
        f"Привет! Вы пришли от партнера с кодом {partner_code}. Выберите действие:",
        reply_markup=main_keyboard,
    )


@router.message(UserForm.waiting_start, F.text == "📄 Документы")
async def show_documents(message: Message, state: FSMContext) -> None:
    settings = get_settings()
    if not settings.documents:
        await message.answer("Документы не настроены.")
        return

    await message.answer(
        "Выберите документ:",
        reply_markup=documents_keyboard(settings.documents),
    )


@router.callback_query(F.data == "action:documents")
async def action_documents(callback: CallbackQuery, state: FSMContext) -> None:
    settings = get_settings()
    if not settings.documents:
        await callback.message.edit_text("Документы не настроены.", reply_markup=inline_main_keyboard)
        await callback.answer()
        return

    await callback.message.edit_text(
        "Выберите документ:",
        reply_markup=documents_keyboard(settings.documents)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("doc:"))
async def send_document(callback: CallbackQuery, state: FSMContext) -> None:
    doc_id = callback.data.split(":", 1)[1]
    settings = get_settings()
    doc = next((d for d in settings.documents if d["id"] == doc_id), None)

    if not doc:
        await callback.answer("Документ не найден.")
        return

    await callback.answer()

    if doc["type"] == "text":
        await callback.message.answer(doc["content"])
    elif doc["type"] == "file":
        file_path = doc.get("path")
        if file_path and Path(file_path).exists():
            await callback.message.answer_document(FSInputFile(file_path), caption=doc["title"])
        else:
            await callback.message.answer(f"Файл {file_path} не найден.")

    await callback.message.answer("Что дальше?", reply_markup=inline_main_keyboard)


@router.message(UserForm.waiting_start, F.text == "📅 Записаться на консультацию")
async def start_consultation(message: Message, state: FSMContext) -> None:
    await state.set_state(UserForm.consultation_consent)
    await message.answer(
        "Для записи на консультацию нужно предоставить персональные данные (имя, телефон). "
        "Вы согласны на обработку данных в соответствии с политикой конфиденциальности?",
        reply_markup=consent_keyboard,
    )


@router.callback_query(F.data == "action:consultation", UserForm.waiting_start)
async def action_consultation(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(UserForm.consultation_consent)
    await callback.message.edit_text(
        "Для записи на консультацию нужно предоставить персональные данные (имя, телефон). "
        "Вы согласны на обработку данных в соответствии с политикой конфиденциальности?",
        reply_markup=consent_keyboard
    )
    await callback.answer()


@router.callback_query(F.data == "consent_yes", UserForm.consultation_consent)
async def consent_yes(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(UserForm.consultation_name)
    await callback.message.edit_text("Введите ваше имя:")
    await callback.answer()


@router.callback_query(F.data == "consent_no", UserForm.consultation_consent)
async def consent_no(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text("Запись отменена. Выберите другое действие:", reply_markup=inline_main_keyboard)
    await callback.answer()


@router.message(UserForm.consultation_name)
async def process_name(message: Message, state: FSMContext) -> None:
    name = message.text.strip()
    if not is_valid_name(name):
        await message.answer("Имя должно содержать 2-50 символов (буквы, пробелы). Попробуйте снова.")
        return

    await state.update_data(name=name)
    await state.set_state(UserForm.consultation_phone)
    await message.answer("Введите номер телефона (можно поделиться контактом):")


@router.message(UserForm.consultation_phone, F.contact)
async def process_phone_contact(message: Message, state: FSMContext, db: Database) -> None:
    contact = message.contact
    if contact and contact.phone_number:
        await _process_phone(contact.phone_number, message, state, db)
    else:
        await message.answer("Не удалось прочитать телефон. Введите вручную.")


@router.message(UserForm.consultation_phone)
async def process_phone_text(message: Message, state: FSMContext, db: Database) -> None:
    await _process_phone(message.text or "", message, state, db)


async def _process_phone(phone_raw: str, message: Message, state: FSMContext, db: Database) -> None:
    if not is_valid_phone(phone_raw):
        await message.answer("Неверный формат телефона. Укажите 10-15 цифр.")
        return

    phone = normalize_phone(phone_raw)
    data = await state.get_data()
    partner_code = data.get("partner_code")
    name = data.get("name")
    user_id = message.from_user.id if message.from_user else 0

    if not partner_code or not name:
        await message.answer("Ошибка данных. Начните заново /start <код>.")
        await state.clear()
        return

    try:
        bitrix_lead_id = await create_lead(name, phone, partner_code)  # Changed from create_deal
        await db.save_request(user_id, partner_code, name, phone, bitrix_lead_id)  # Still using bitrix_deal_id field
        await message.answer(
            f"Заявка создана! Лид в Bitrix: {bitrix_lead_id}\n"  # Changed text from "Сделка" to "Лид"
            f"Менеджер свяжется с вами по телефону {phone}.",
            reply_markup=main_keyboard,
        )
        await state.clear()
    except BitrixNotConfiguredError:
        await message.answer("Ошибка: Bitrix не настроен. Свяжитесь с администратором.")
        await state.clear()
    except Exception as e:
        logger.error(f"Ошибка создания лида: {e}")  # Changed from "сделки" to "лида"
        await message.answer("Ошибка при создании заявки. Попробуйте позже.")
        await state.clear()


@router.message(Command("cancel"))
async def cancel_handler(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Действие отменено.", reply_markup=main_keyboard)


@router.message(F.text)
async def fallback_handler(message: Message, state: FSMContext, db: Database) -> None:
    """Fallback для инициализации state для существующих пользователей."""
    current_state = await state.get_state()
    if current_state is None:
        user = message.from_user
        if user:
            existing_request = await db.get_request_by_user(user.id)
            if existing_request:
                await state.set_state(UserForm.waiting_start)
                await state.update_data(partner_code=existing_request['partner_code'])  # Dict access
                await message.answer(
                    "Вы уже зарегистрированы. Используйте кнопки ниже для действий.",
                    reply_markup=main_keyboard,
                )
                return
    await message.answer("Неизвестная команда. Используйте /start <код_партнера> для начала.")