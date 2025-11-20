from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

request_phone_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="Поделиться номером", request_contact=True),
        ]
    ],
    resize_keyboard=True,
    one_time_keyboard=True,
    input_field_placeholder="Отправьте номер телефона",
)


def hide_keyboard() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()


def stats_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📊 Сегодня", callback_data="stats:today"),
            ],
            [
                InlineKeyboardButton(text="📈 Неделя", callback_data="stats:week"),
            ],
            [
                InlineKeyboardButton(text="📆 Всё время", callback_data="stats:all"),
            ]
        ]
    )

