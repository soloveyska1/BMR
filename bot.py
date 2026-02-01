import asyncio
import logging
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.filters import Command
from aiogram.enums import ParseMode

from config import BOT_TOKEN, CHANNEL_ID, ADMIN_IDS, AUTO_REPLY_TEXT


def is_admin(user_id: int) -> bool:
    """Проверить, является ли пользователь админом"""
    return user_id in ADMIN_IDS
from database import (
    init_db,
    save_message,
    toggle_starred,
    toggle_hidden,
    get_starred_messages,
    get_stats,
    get_message_by_channel_id,
)

# Логирование
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Инициализация бота
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


def get_inline_keyboard(message_db_id: int, is_starred: bool = False) -> InlineKeyboardMarkup:
    """Создать inline-клавиатуру для сообщения"""
    star_text = "⭐ Убрать из избранного" if is_starred else "⭐ В избранное"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=star_text,
                    callback_data=f"star:{message_db_id}"
                ),
                InlineKeyboardButton(
                    text="🗑 Скрыть",
                    callback_data=f"hide:{message_db_id}"
                ),
            ]
        ]
    )


def format_message_header(user_id: int, username: str, full_name: str, created_at: datetime) -> str:
    """Форматировать заголовок сообщения"""
    # Формируем ссылку на пользователя
    if username:
        user_link = f"@{username}"
    else:
        user_link = f"<a href='tg://user?id={user_id}'>{full_name}</a>"

    # Форматируем дату
    if isinstance(created_at, str):
        dt = datetime.fromisoformat(created_at)
    else:
        dt = created_at

    date_str = dt.strftime("%d.%m.%Y, %H:%M")

    return f"👤 {user_link} ({full_name})\n📅 {date_str}\n\n"


# ============ ОБРАБОТЧИКИ СООБЩЕНИЙ ============

@dp.message(Command("start"))
async def cmd_start(message: Message):
    """Обработчик команды /start"""
    # Если это админ
    if is_admin(message.from_user.id):
        await message.answer(
            "👋 Привет, админ!\n\n"
            "Доступные команды:\n"
            "/starred — показать избранные сообщения\n"
            "/stats — статистика\n\n"
            "Все входящие сообщения пересылаются в твой канал."
        )
    else:
        await message.answer(
            "👋 Привет!\n\n"
            "Напиши мне своё сообщение, и оно будет передано автору.\n"
            "Можешь отправить текст, фото или голосовое сообщение."
        )


@dp.message(Command("starred"))
async def cmd_starred(message: Message):
    """Показать избранные сообщения"""
    if not is_admin(message.from_user.id):
        return

    messages = await get_starred_messages(limit=20)

    if not messages:
        await message.answer("⭐ Избранных сообщений пока нет.")
        return

    await message.answer(f"⭐ Избранные сообщения ({len(messages)}):\n")

    for msg in messages:
        header = format_message_header(
            msg["user_id"],
            msg["username"],
            msg["full_name"],
            msg["created_at"]
        )
        text = msg["text"] or "[медиа]"
        await message.answer(
            f"{header}{text}",
            parse_mode=ParseMode.HTML
        )


@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    """Показать статистику"""
    if not is_admin(message.from_user.id):
        return

    stats = await get_stats()

    await message.answer(
        f"📊 <b>Статистика</b>\n\n"
        f"📨 Всего сообщений: {stats['total']}\n"
        f"📅 За сегодня: {stats['today']}\n"
        f"📆 За неделю: {stats['week']}\n"
        f"⭐ Избранных: {stats['starred']}\n"
        f"👥 Уникальных пользователей: {stats['unique_users']}",
        parse_mode=ParseMode.HTML
    )


@dp.message(F.text | F.photo | F.voice | F.video | F.video_note | F.document)
async def handle_user_message(message: Message):
    """Обработка входящих сообщений от пользователей"""
    # Игнорируем сообщения от админов (кроме команд)
    if is_admin(message.from_user.id):
        return

    user = message.from_user
    username = user.username or ""
    full_name = user.full_name or "Без имени"

    # Формируем заголовок
    header = format_message_header(
        user.id,
        username,
        full_name,
        datetime.now()
    )

    # Определяем тип контента и пересылаем
    has_photo = False
    text_content = message.text or message.caption or ""

    try:
        if message.photo:
            # Фото
            has_photo = True
            sent_msg = await bot.send_photo(
                chat_id=CHANNEL_ID,
                photo=message.photo[-1].file_id,  # Лучшее качество
                caption=f"{header}{text_content}",
                parse_mode=ParseMode.HTML
            )
        elif message.voice:
            # Голосовое
            sent_msg = await bot.send_voice(
                chat_id=CHANNEL_ID,
                voice=message.voice.file_id,
                caption=header,
                parse_mode=ParseMode.HTML
            )
        elif message.video:
            # Видео
            sent_msg = await bot.send_video(
                chat_id=CHANNEL_ID,
                video=message.video.file_id,
                caption=f"{header}{text_content}",
                parse_mode=ParseMode.HTML
            )
        elif message.video_note:
            # Кружок
            # Сначала отправляем заголовок, потом кружок
            await bot.send_message(
                chat_id=CHANNEL_ID,
                text=header,
                parse_mode=ParseMode.HTML
            )
            sent_msg = await bot.send_video_note(
                chat_id=CHANNEL_ID,
                video_note=message.video_note.file_id
            )
        elif message.document:
            # Документ
            sent_msg = await bot.send_document(
                chat_id=CHANNEL_ID,
                document=message.document.file_id,
                caption=f"{header}{text_content}",
                parse_mode=ParseMode.HTML
            )
        else:
            # Текст
            sent_msg = await bot.send_message(
                chat_id=CHANNEL_ID,
                text=f"{header}{text_content}",
                parse_mode=ParseMode.HTML
            )

        # Сохраняем в БД
        msg_id = await save_message(
            telegram_message_id=message.message_id,
            channel_message_id=sent_msg.message_id,
            user_id=user.id,
            username=username,
            full_name=full_name,
            text=text_content,
            has_photo=has_photo
        )

        # Добавляем кнопки (редактируем сообщение)
        keyboard = get_inline_keyboard(msg_id, is_starred=False)

        # Для сообщений с медиа используем edit_caption, для текста - edit_text
        if message.photo or message.video or message.document:
            await sent_msg.edit_caption(
                caption=f"{header}{text_content}",
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML
            )
        elif message.voice:
            await sent_msg.edit_caption(
                caption=header,
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML
            )
        elif not message.video_note:
            await sent_msg.edit_text(
                text=f"{header}{text_content}",
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML
            )

        # Отправляем автоответ пользователю
        await message.answer(AUTO_REPLY_TEXT)

        logger.info(f"Сообщение от {full_name} (@{username}) переслано в канал")

    except Exception as e:
        logger.error(f"Ошибка при пересылке сообщения: {e}")
        await message.answer("❌ Произошла ошибка при отправке. Попробуйте позже.")


# ============ ОБРАБОТЧИКИ CALLBACK ============

@dp.callback_query(F.data.startswith("star:"))
async def callback_star(callback: CallbackQuery):
    """Обработка нажатия на кнопку избранного"""
    message_db_id = int(callback.data.split(":")[1])
    new_status = await toggle_starred(message_db_id)

    # Обновляем клавиатуру
    keyboard = get_inline_keyboard(message_db_id, is_starred=new_status)

    try:
        if callback.message.text:
            await callback.message.edit_reply_markup(reply_markup=keyboard)
        else:
            await callback.message.edit_reply_markup(reply_markup=keyboard)
    except Exception:
        pass

    status_text = "добавлено в избранное ⭐" if new_status else "убрано из избранного"
    await callback.answer(f"Сообщение {status_text}")


@dp.callback_query(F.data.startswith("hide:"))
async def callback_hide(callback: CallbackQuery):
    """Обработка нажатия на кнопку скрытия"""
    message_db_id = int(callback.data.split(":")[1])
    await toggle_hidden(message_db_id)

    # Удаляем сообщение из канала
    try:
        await callback.message.delete()
    except Exception:
        pass

    await callback.answer("🗑 Сообщение скрыто")


# ============ ЗАПУСК ============

async def main():
    """Главная функция запуска бота"""
    # Инициализируем БД
    await init_db()

    logger.info("Бот запущен!")
    logger.info(f"Канал для пересылки: {CHANNEL_ID}")
    logger.info(f"Админы: {ADMIN_IDS}")

    # Запускаем поллинг
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
