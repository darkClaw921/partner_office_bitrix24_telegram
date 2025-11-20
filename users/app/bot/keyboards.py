from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📄 Документы")],
        [KeyboardButton(text="📅 Записаться на консультацию")],
    ],
    resize_keyboard=True,
    input_field_placeholder="Выберите действие",
)


def documents_keyboard(documents: list) -> InlineKeyboardMarkup:
    inline_keyboard = [
        [InlineKeyboardButton(text=doc["title"], callback_data=f"doc:{doc['id']}")] for doc in documents
    ]
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


consent_keyboard = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="✅ Согласен", callback_data="consent_yes")],
        [InlineKeyboardButton(text="❌ Отказаться", callback_data="consent_no")],
    ]
)


def hide_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[], resize_keyboard=True, one_time_keyboard=True)
inline_main_keyboard = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="📄 Документы", callback_data="action:documents")],
        [InlineKeyboardButton(text="📅 Записаться на консультацию", callback_data="action:consultation")],
    ]
)