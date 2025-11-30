from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from loguru import logger

from app.bot.keyboards import (
    detailed_stats_keyboard,
    hide_keyboard,
    request_phone_keyboard,
    stats_keyboard,
)
from app.db.database import Database
from app.services.models import PartnerSubmission
from app.services.stats import (
    DealStats,
    DetailedStats,
    fetch_deal_stats,
    fetch_detailed_stats,
)
from app.utils.validators import (
    is_valid_partner_code,
    is_valid_phone,
    normalize_partner_code,
    normalize_phone,
)
from app.utils.workBitrix24 import (
    BitrixNotConfiguredError,
    PartnerContact,
    fetch_partner_percent,
    find_partner_contact_by_phone,
    get_bitrix_service,
)

router = Router(name="partner_registration")


class RegistrationForm(StatesGroup):
    phone = State()
    partner_code = State()
    authorized = State()


@router.message(Command("cancel"))
@router.message(Command("stop"))
async def cancel_registration(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Форма сброшена. Отправьте /start, чтобы начать сначала.", reply_markup=hide_keyboard())


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, db: Database) -> None:
    user = message.from_user
    if user:
        existing_submission = await db.get_submission_by_user(user.id)
        if existing_submission:
            bitrix_contact_id = existing_submission.get("bitrix_contact_id")
            if bitrix_contact_id is None:
                await state.clear()
                await message.answer(
                    "Вы уже авторизованы, но контакт Bitrix не найден. Свяжитесь с администратором для уточнения."
                )
                return

            partner_percent = await _safe_fetch_partner_percent(int(bitrix_contact_id))
            await state.set_state(RegistrationForm.authorized)
            await state.update_data(
                bitrix_contact_id=int(bitrix_contact_id),
                bitrix_entity_type=existing_submission.get("bitrix_entity_type"),  # Add entity type
                partner_percent=partner_percent,
            )
            await message.answer(
                "Вы уже авторизованы и можете сразу запросить статистику.",
                reply_markup=stats_keyboard(),
            )
            return

    await state.set_state(RegistrationForm.phone)
    await message.answer(
        "Привет! Отправьте пожалуйста номер телефона. Вы можете поделиться контактом кнопкой ниже.",
        reply_markup=request_phone_keyboard,
    )


@router.message(RegistrationForm.phone, F.contact)
async def process_phone_from_contact(message: Message, state: FSMContext) -> None:
    contact = message.contact
    if contact is None:
        await message.answer("Не удалось прочитать контакт. Попробуйте снова или введите номер вручную.")
        return

    if contact.user_id and message.from_user and contact.user_id != message.from_user.id:
        await message.answer("Можно отправлять только собственный контакт.")
        return

    await _process_phone_value(contact.phone_number or "", message, state)


@router.message(RegistrationForm.phone, ~F.contact)
async def process_phone_from_text(message: Message, state: FSMContext) -> None:
    await _process_phone_value(message.text or "", message, state)


async def _process_phone_value(value: str, message: Message, state: FSMContext) -> None:
    if not is_valid_phone(value):
        await message.answer("Похоже, номер некорректный. Убедитесь, что указали от 10 до 15 цифр.")
        return

    normalized_phone = normalize_phone(value)
    try:
        partner_contact = await find_partner_contact_by_phone(normalized_phone)
    except BitrixNotConfiguredError:
        logger.error("Bitrix webhook не настроен, авторизация невозможна")
        await message.answer("Авторизация партнёров временно недоступна. Сообщите администратору.")
        await state.clear()
        return

    if partner_contact is None:
        await message.answer(
            "Партнёр с таким номером не найден или не содержит кода. Уточните данные и попробуйте снова."
        )
        return

    # Use entity type from PartnerContact object
    entity_type = partner_contact.entity_type
    logger.info(f"PARTNER_CODE: {partner_contact.partner_code}")

    await state.update_data(
        phone=normalized_phone,
        bitrix_contact_id=partner_contact.id,
        bitrix_entity_type=entity_type,
        expected_partner_code=partner_contact.partner_code,
        partner_percent=partner_contact.percent,
    )
    await state.set_state(RegistrationForm.partner_code)
    await message.answer(
        "Спасибо! Теперь отправьте код партнёра (латинские буквы, цифры, -, _).",
        reply_markup=hide_keyboard(),
    )


@router.message(RegistrationForm.partner_code)
async def process_partner_code(message: Message, state: FSMContext, db: Database) -> None:
    partner_code_raw = (message.text or "").strip()
    if not is_valid_partner_code(partner_code_raw):
        await message.answer("Код должен содержать 3-32 символа: A-Z, 0-9, -, _. Попробуйте снова.")
        return

    partner_code = normalize_partner_code(partner_code_raw)
    user = message.from_user
    data = await state.get_data()
    phone = data.get("phone")
    expected_code = data.get("expected_partner_code")
    bitrix_contact_id = data.get("bitrix_contact_id")
    
    if expected_code is not None:
        expected_code = normalize_partner_code(expected_code)
    if not phone or not expected_code or not bitrix_contact_id:
        await message.answer("Не удалось найти номер телефона, начните заново командой /start.")
        await state.clear()
        return

    if partner_code != expected_code:
        logger.error(f"Код не совпадает с указанным в Bitrix24. expected_code: {expected_code}, partner_code: {partner_code}")
        await message.answer("Код не совпадает с указанным в Bitrix24. Попробуйте снова.")
        return

    submission = PartnerSubmission(
        user_id=user.id if user else 0,
        username=user.username if user else None,
        first_name=user.first_name if user else None,
        last_name=user.last_name if user else None,
        phone_number=phone,
        partner_code=partner_code,
        bitrix_contact_id=int(bitrix_contact_id),
        bitrix_entity_type=data.get("bitrix_entity_type"),  # Add entity type to submission
    )

    await db.save_submission(submission, data.get("bitrix_entity_type"))
    await state.set_state(RegistrationForm.authorized)
    await state.update_data(
        bitrix_contact_id=submission.bitrix_contact_id,
        partner_percent=data.get("partner_percent"),
    )
    await message.answer(
        "Авторизация успешна! Теперь вы можете запросить статистику по своим сделкам.",
        reply_markup=stats_keyboard(),
    )
    logger.info("Новая регистрация: пользователь {} с телефоном {}", submission.user_id, submission.phone_number)


@router.callback_query(F.data.startswith("stats:"), RegistrationForm.authorized)
async def handle_stats_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    range_key = callback.data.split(":", maxsplit=1)[1]
    data = await state.get_data()
    bitrix_contact_id = data.get("bitrix_contact_id")
    bitrix_entity_type = data.get("bitrix_entity_type")  # Get entity type
    if not bitrix_contact_id:
        await callback.message.answer("Не удалось определить контакта Bitrix. Авторизуйтесь заново командой /start.")
        await state.clear()
        return

    partner_percent = data.get("partner_percent")
    if partner_percent is None:
        partner_percent = await _safe_fetch_partner_percent(int(bitrix_contact_id))  # type: ignore[arg-type]
        await state.update_data(partner_percent=partner_percent)

    # Pass entity type to fetch_deal_stats
    stats = await fetch_deal_stats(int(bitrix_contact_id), range_key, entity_type=bitrix_entity_type)  # type: ignore[arg-type]
    await callback.message.answer(
        _format_stats(range_key, stats, partner_percent),
        reply_markup=detailed_stats_keyboard(range_key),
    )


def _format_stats(range_key: str, stats: DealStats, partner_percent: float | None) -> str:
    titles = {
        "today": "Статистика за сегодня",
        "week": "Статистика за неделю",
        "all": "Статистика за всё время",
    }
    title = titles.get(range_key, "Статистика")
    partner_line = ""
    if partner_percent is not None:
        partner_amount = stats.total_amount * (partner_percent / 100)
        partner_line = f"\nВаш процент: {partner_percent:.2f}%\nСумма по проценту: {partner_amount:.2f}"
    return (
        f"{title}\n"
        f"В работе: {stats.in_progress} (сумма {stats.in_progress_amount:.2f})\n"
        f"Успешно: {stats.success} (сумма {stats.success_amount:.2f})\n"
        f"Провалено: {stats.failed} (сумма {stats.failed_amount:.2f})\n"
        f"Итого: {stats.total_amount:.2f}"
        f"{partner_line}"
    )


@router.callback_query(F.data.startswith("detailed_stats:"), RegistrationForm.authorized)
async def handle_detailed_stats_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    range_key = callback.data.split(":", maxsplit=1)[1]
    data = await state.get_data()
    bitrix_contact_id = data.get("bitrix_contact_id")
    bitrix_entity_type = data.get("bitrix_entity_type")
    if not bitrix_contact_id:
        await callback.message.answer("Не удалось определить контакта Bitrix. Авторизуйтесь заново командой /start.")
        await state.clear()
        return

    try:
        detailed_stats = await fetch_detailed_stats(
            int(bitrix_contact_id),
            range_key,
            entity_type=bitrix_entity_type  # type: ignore[arg-type]
        )
        message_text = _format_detailed_stats(range_key, detailed_stats)
        await callback.message.answer(
            message_text,
            reply_markup=detailed_stats_keyboard(range_key),
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("Ошибка при получении детальной статистики")
        await callback.message.answer(
            f"Не удалось получить детальную статистику: {str(e)}",
            reply_markup=detailed_stats_keyboard(range_key),
        )


def _format_detailed_stats(range_key: str, detailed_stats: DetailedStats) -> str:
    """Форматирует детальную статистику для отображения."""
    titles = {
        "today": "Детальная статистика за сегодня",
        "week": "Детальная статистика за неделю",
        "all": "Детальная статистика за всё время",
    }
    title = titles.get(range_key, "Детальная статистика")
    
    if not detailed_stats.clients:
        return f"{title}\n\nСделки не найдены."
    
    lines = [title, ""]
    
    # Display detailed stats for each client in the same format as main stats
    for client in detailed_stats.clients:
        lines.append(f"👤 {client.client_name}")
        lines.append(f"В работе: {client.deals_in_progress} (сумма {client.in_progress_amount:.2f})")
        lines.append(f"Успешно: {client.deals_success} (сумма {client.success_amount:.2f})")
        lines.append(f"Провалено: {client.deals_failed} (сумма {client.failed_amount:.2f})")
        lines.append(f"Итого: {client.total_amount:.2f}")
        
        lines.append("")
    
    return "\n".join(lines)


async def _safe_fetch_partner_percent(contact_id: int) -> float | None:
    try:
        return await fetch_partner_percent(contact_id)
    except BitrixNotConfiguredError:
        logger.error("Bitrix webhook не настроен, получение процента невозможно")
        return None
    except Exception:  # noqa: BLE001
        logger.exception("Не удалось получить процент партнёра {}", contact_id)
        return None