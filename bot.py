import asyncio
import logging
import json
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    FSInputFile,
)
from aiogram.filters import Command, CommandObject
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import BOT_TOKEN, CHANNEL_ID, ADMIN_IDS, AUTO_REPLY_TEXT
from database import (
    init_db,
    save_message,
    get_message_by_id,
    toggle_starred,
    toggle_hidden,
    mark_as_read,
    set_category,
    save_reply,
    get_starred_messages,
    get_unread_messages,
    get_messages_by_category,
    search_messages,
    get_stats,
    export_messages,
)

# Логирование
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Инициализация бота
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# ============ СОСТОЯНИЯ FSM ============

class ReplyState(StatesGroup):
    waiting_for_reply = State()


# ============ ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ============

def is_admin(user_id: int) -> bool:
    """Проверить, является ли пользователь админом"""
    return user_id in ADMIN_IDS


# Категории
CATEGORIES = {
    "question": "❓ Вопрос",
    "review": "💬 Отзыв",
    "idea": "💡 Идея",
    "thanks": "🙏 Благодарность",
    "problem": "⚠️ Проблема",
}


def get_inline_keyboard(message_db_id: int, is_starred: bool = False, category: str = None) -> InlineKeyboardMarkup:
    """Создать inline-клавиатуру для сообщения"""
    star_emoji = "★" if is_starred else "☆"

    buttons = [
        # Первый ряд - основные действия
        [
            InlineKeyboardButton(text=f"{star_emoji} Избранное", callback_data=f"star:{message_db_id}"),
            InlineKeyboardButton(text="💬 Ответить", callback_data=f"reply:{message_db_id}"),
            InlineKeyboardButton(text="🗑", callback_data=f"hide:{message_db_id}"),
        ],
        # Второй ряд - категории
        [
            InlineKeyboardButton(text="❓", callback_data=f"cat:{message_db_id}:question"),
            InlineKeyboardButton(text="💬", callback_data=f"cat:{message_db_id}:review"),
            InlineKeyboardButton(text="💡", callback_data=f"cat:{message_db_id}:idea"),
            InlineKeyboardButton(text="🙏", callback_data=f"cat:{message_db_id}:thanks"),
            InlineKeyboardButton(text="⚠️", callback_data=f"cat:{message_db_id}:problem"),
        ],
        # Третий ряд - отметить прочитанным
        [
            InlineKeyboardButton(text="✅ Прочитано", callback_data=f"read:{message_db_id}"),
        ]
    ]

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def format_message_header(
    msg_id: int,
    user_id: int,
    username: str,
    full_name: str,
    created_at: datetime,
    is_starred: bool = False,
    is_read: bool = False,
    category: str = None,
    has_reply: bool = False
) -> str:
    """Форматировать заголовок сообщения"""

    # Статусы
    status_icons = []
    if not is_read:
        status_icons.append("🆕")
    if is_starred:
        status_icons.append("⭐")
    if has_reply:
        status_icons.append("↩️")
    if category and category in CATEGORIES:
        status_icons.append(CATEGORIES[category].split()[0])

    status_line = " ".join(status_icons) if status_icons else ""

    # Ссылка на пользователя
    if username:
        user_link = f"@{username}"
    else:
        user_link = f"<a href='tg://user?id={user_id}'>{full_name}</a>"

    # Форматируем дату
    if isinstance(created_at, str):
        dt = datetime.fromisoformat(created_at)
    else:
        dt = created_at
    date_str = dt.strftime("%d.%m.%Y в %H:%M")

    # Собираем заголовок
    header = f"{'━' * 20}\n"
    header += f"📩 <b>Сообщение #{msg_id}</b> {status_line}\n"
    header += f"👤 {user_link}\n"
    header += f"📝 {full_name}\n"
    header += f"🕐 {date_str}\n"
    header += f"{'━' * 20}\n\n"

    return header


def format_short_message(msg) -> str:
    """Короткий формат сообщения для списков"""
    text = msg["text"] or "[медиа]"
    if len(text) > 50:
        text = text[:50] + "..."

    status = ""
    if msg["is_starred"]:
        status += "⭐"
    if not msg["is_read"]:
        status += "🆕"

    return f"#{msg['id']} {status} <b>{msg['full_name']}</b>: {text}"


# ============ КОМАНДЫ ============

@dp.message(Command("start"))
async def cmd_start(message: Message):
    """Обработчик команды /start"""
    if is_admin(message.from_user.id):
        stats = await get_stats()
        await message.answer(
            f"👋 <b>Привет, админ!</b>\n\n"
            f"📊 <b>Быстрая сводка:</b>\n"
            f"├ 📨 Всего сообщений: {stats['total']}\n"
            f"├ 🆕 Непрочитанных: {stats['unread']}\n"
            f"├ ⭐ Избранных: {stats['starred']}\n"
            f"└ 👥 Пользователей: {stats['unique_users']}\n\n"
            f"📋 <b>Команды:</b>\n"
            f"/unread — непрочитанные сообщения\n"
            f"/starred — избранные сообщения\n"
            f"/stats — подробная статистика\n"
            f"/search <i>текст</i> — поиск\n"
            f"/export — выгрузить всё в файл\n"
            f"/cat <i>категория</i> — по категориям\n\n"
            f"💡 <i>Категории: question, review, idea, thanks, problem</i>",
            parse_mode=ParseMode.HTML
        )
    else:
        await message.answer(
            "👋 <b>Привет!</b>\n\n"
            "Напиши мне своё сообщение, и оно будет передано автору.\n\n"
            "📝 Можешь отправить:\n"
            "├ Текст\n"
            "├ Фото\n"
            "├ Голосовое сообщение\n"
            "├ Видео\n"
            "└ Документ\n\n"
            "✨ <i>Каждое сообщение важно!</i>",
            parse_mode=ParseMode.HTML
        )


@dp.message(Command("unread"))
async def cmd_unread(message: Message):
    """Показать непрочитанные сообщения"""
    if not is_admin(message.from_user.id):
        return

    messages = await get_unread_messages(limit=20)

    if not messages:
        await message.answer("✅ Все сообщения прочитаны!")
        return

    text = f"🆕 <b>Непрочитанные сообщения ({len(messages)}):</b>\n\n"
    for msg in messages:
        text += format_short_message(msg) + "\n"

    await message.answer(text, parse_mode=ParseMode.HTML)


@dp.message(Command("starred"))
async def cmd_starred(message: Message):
    """Показать избранные сообщения"""
    if not is_admin(message.from_user.id):
        return

    messages = await get_starred_messages(limit=20)

    if not messages:
        await message.answer("⭐ Избранных сообщений пока нет.")
        return

    text = f"⭐ <b>Избранные сообщения ({len(messages)}):</b>\n\n"
    for msg in messages:
        text += format_short_message(msg) + "\n"

    await message.answer(text, parse_mode=ParseMode.HTML)


@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    """Показать подробную статистику"""
    if not is_admin(message.from_user.id):
        return

    stats = await get_stats()

    # Формируем топ пользователей
    top_users_text = ""
    for i, (name, username, count) in enumerate(stats["top_users"], 1):
        medal = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"][i-1] if i <= 5 else f"{i}."
        user_display = f"@{username}" if username else name
        top_users_text += f"{medal} {user_display}: {count} сообщ.\n"

    # Формируем категории
    cat_text = ""
    for cat, count in stats["categories"].items():
        cat_text += f"├ {CATEGORIES.get(cat, cat)}: {count}\n"
    if not cat_text:
        cat_text = "├ <i>нет данных</i>\n"

    await message.answer(
        f"📊 <b>СТАТИСТИКА</b>\n\n"
        f"📨 <b>Сообщения:</b>\n"
        f"├ Всего: {stats['total']}\n"
        f"├ За сегодня: {stats['today']}\n"
        f"├ За неделю: {stats['week']}\n"
        f"├ 🆕 Непрочитанных: {stats['unread']}\n"
        f"├ ⭐ Избранных: {stats['starred']}\n"
        f"└ ↩️ С ответами: {stats['replied']}\n\n"
        f"👥 <b>Пользователи:</b>\n"
        f"└ Уникальных: {stats['unique_users']}\n\n"
        f"🏆 <b>Топ активных:</b>\n{top_users_text}\n"
        f"🏷 <b>По категориям:</b>\n{cat_text}",
        parse_mode=ParseMode.HTML
    )


@dp.message(Command("search"))
async def cmd_search(message: Message, command: CommandObject):
    """Поиск по сообщениям"""
    if not is_admin(message.from_user.id):
        return

    if not command.args:
        await message.answer("❓ Укажи текст для поиска: /search <i>слово</i>", parse_mode=ParseMode.HTML)
        return

    query = command.args
    messages = await search_messages(query)

    if not messages:
        await message.answer(f"🔍 По запросу «{query}» ничего не найдено.")
        return

    text = f"🔍 <b>Результаты поиска «{query}»:</b>\n\n"
    for msg in messages:
        text += format_short_message(msg) + "\n"

    await message.answer(text, parse_mode=ParseMode.HTML)


@dp.message(Command("cat"))
async def cmd_category(message: Message, command: CommandObject):
    """Показать сообщения по категории"""
    if not is_admin(message.from_user.id):
        return

    if not command.args or command.args not in CATEGORIES:
        cats = "\n".join([f"├ <code>{k}</code> — {v}" for k, v in CATEGORIES.items()])
        await message.answer(
            f"🏷 <b>Доступные категории:</b>\n{cats}\n\n"
            f"Используй: /cat <code>категория</code>",
            parse_mode=ParseMode.HTML
        )
        return

    category = command.args
    messages = await get_messages_by_category(category)

    if not messages:
        await message.answer(f"🏷 В категории {CATEGORIES[category]} пока нет сообщений.")
        return

    text = f"🏷 <b>{CATEGORIES[category]} ({len(messages)}):</b>\n\n"
    for msg in messages:
        text += format_short_message(msg) + "\n"

    await message.answer(text, parse_mode=ParseMode.HTML)


@dp.message(Command("export"))
async def cmd_export(message: Message):
    """Экспорт сообщений в файл"""
    if not is_admin(message.from_user.id):
        return

    await message.answer("📦 Готовлю экспорт...")

    messages = await export_messages()

    if not messages:
        await message.answer("📭 Нет сообщений для экспорта.")
        return

    # Формируем данные
    export_data = []
    for msg in messages:
        export_data.append({
            "id": msg["id"],
            "user_id": msg["user_id"],
            "username": msg["username"],
            "full_name": msg["full_name"],
            "text": msg["text"],
            "is_starred": bool(msg["is_starred"]),
            "category": msg["category"],
            "created_at": msg["created_at"],
            "reply_text": msg["reply_text"],
        })

    # Сохраняем в файл
    filename = f"export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(export_data, f, ensure_ascii=False, indent=2)

    # Отправляем файл
    await message.answer_document(
        FSInputFile(filename),
        caption=f"📦 Экспорт {len(export_data)} сообщений"
    )

    # Удаляем временный файл
    import os
    os.remove(filename)


# ============ ОБРАБОТКА СООБЩЕНИЙ ОТ ПОЛЬЗОВАТЕЛЕЙ ============

@dp.message(F.text | F.photo | F.voice | F.video | F.video_note | F.document)
async def handle_user_message(message: Message, state: FSMContext):
    """Обработка входящих сообщений"""

    # Проверяем, ждём ли мы ответ от админа
    current_state = await state.get_state()
    if current_state == ReplyState.waiting_for_reply.state:
        await handle_admin_reply(message, state)
        return

    # Игнорируем сообщения от админов (кроме ответов)
    if is_admin(message.from_user.id):
        return

    user = message.from_user
    username = user.username or ""
    full_name = user.full_name or "Без имени"

    # Определяем тип контента
    has_photo = bool(message.photo)
    has_voice = bool(message.voice)
    has_video = bool(message.video or message.video_note)
    text_content = message.text or message.caption or ""

    try:
        # Сначала сохраняем в БД чтобы получить ID
        msg_id = await save_message(
            telegram_message_id=message.message_id,
            channel_message_id=0,  # Обновим после отправки
            user_id=user.id,
            username=username,
            full_name=full_name,
            text=text_content,
            has_photo=has_photo,
            has_voice=has_voice,
            has_video=has_video
        )

        # Формируем заголовок с номером сообщения
        header = format_message_header(
            msg_id=msg_id,
            user_id=user.id,
            username=username,
            full_name=full_name,
            created_at=datetime.now(),
            is_starred=False,
            is_read=False,
            category=None,
            has_reply=False
        )

        # Получаем клавиатуру
        keyboard = get_inline_keyboard(msg_id, is_starred=False)

        # Отправляем в канал
        if message.photo:
            sent_msg = await bot.send_photo(
                chat_id=CHANNEL_ID,
                photo=message.photo[-1].file_id,
                caption=f"{header}{text_content}",
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard
            )
        elif message.voice:
            sent_msg = await bot.send_voice(
                chat_id=CHANNEL_ID,
                voice=message.voice.file_id,
                caption=header,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard
            )
        elif message.video:
            sent_msg = await bot.send_video(
                chat_id=CHANNEL_ID,
                video=message.video.file_id,
                caption=f"{header}{text_content}",
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard
            )
        elif message.video_note:
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
            sent_msg = await bot.send_document(
                chat_id=CHANNEL_ID,
                document=message.document.file_id,
                caption=f"{header}{text_content}",
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard
            )
        else:
            sent_msg = await bot.send_message(
                chat_id=CHANNEL_ID,
                text=f"{header}{text_content}",
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard
            )

        # Отправляем автоответ
        await message.answer(AUTO_REPLY_TEXT)

        logger.info(f"Сообщение #{msg_id} от {full_name} (@{username}) переслано")

    except Exception as e:
        logger.error(f"Ошибка при пересылке: {e}")
        await message.answer("❌ Произошла ошибка. Попробуйте позже.")


# ============ ОБРАБОТКА CALLBACK ============

@dp.callback_query(F.data.startswith("star:"))
async def callback_star(callback: CallbackQuery):
    """Переключение избранного"""
    message_db_id = int(callback.data.split(":")[1])
    new_status = await toggle_starred(message_db_id)

    # Обновляем клавиатуру
    msg = await get_message_by_id(message_db_id)
    keyboard = get_inline_keyboard(
        message_db_id,
        is_starred=new_status,
        category=msg["category"] if msg else None
    )

    try:
        await callback.message.edit_reply_markup(reply_markup=keyboard)
    except:
        pass

    status_text = "⭐ Добавлено в избранное" if new_status else "Убрано из избранного"
    await callback.answer(status_text)


@dp.callback_query(F.data.startswith("hide:"))
async def callback_hide(callback: CallbackQuery):
    """Скрыть сообщение"""
    message_db_id = int(callback.data.split(":")[1])
    await toggle_hidden(message_db_id)

    try:
        await callback.message.delete()
    except:
        pass

    await callback.answer("🗑 Сообщение скрыто")


@dp.callback_query(F.data.startswith("read:"))
async def callback_read(callback: CallbackQuery):
    """Отметить прочитанным"""
    message_db_id = int(callback.data.split(":")[1])
    await mark_as_read(message_db_id)

    # Обновляем клавиатуру
    msg = await get_message_by_id(message_db_id)
    keyboard = get_inline_keyboard(
        message_db_id,
        is_starred=bool(msg["is_starred"]) if msg else False,
        category=msg["category"] if msg else None
    )

    try:
        await callback.message.edit_reply_markup(reply_markup=keyboard)
    except:
        pass

    await callback.answer("✅ Отмечено как прочитанное")


@dp.callback_query(F.data.startswith("cat:"))
async def callback_category(callback: CallbackQuery):
    """Установить категорию"""
    parts = callback.data.split(":")
    message_db_id = int(parts[1])
    category = parts[2]

    await set_category(message_db_id, category)

    # Обновляем клавиатуру
    msg = await get_message_by_id(message_db_id)
    keyboard = get_inline_keyboard(
        message_db_id,
        is_starred=bool(msg["is_starred"]) if msg else False,
        category=category
    )

    try:
        await callback.message.edit_reply_markup(reply_markup=keyboard)
    except:
        pass

    await callback.answer(f"🏷 Категория: {CATEGORIES.get(category, category)}")


@dp.callback_query(F.data.startswith("reply:"))
async def callback_reply(callback: CallbackQuery, state: FSMContext):
    """Начать ответ на сообщение"""
    message_db_id = int(callback.data.split(":")[1])
    msg = await get_message_by_id(message_db_id)

    if not msg:
        await callback.answer("❌ Сообщение не найдено")
        return

    # Сохраняем данные для ответа
    await state.update_data(reply_to_msg_id=message_db_id, reply_to_user_id=msg["user_id"])
    await state.set_state(ReplyState.waiting_for_reply)

    await callback.answer()
    await callback.message.answer(
        f"💬 <b>Ответ на сообщение #{message_db_id}</b>\n"
        f"От: {msg['full_name']}\n\n"
        f"Напиши свой ответ (или /cancel для отмены):",
        parse_mode=ParseMode.HTML
    )


@dp.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    """Отмена текущего действия"""
    await state.clear()
    await message.answer("❌ Действие отменено")


async def handle_admin_reply(message: Message, state: FSMContext):
    """Обработка ответа админа"""
    data = await state.get_data()
    reply_to_msg_id = data.get("reply_to_msg_id")
    reply_to_user_id = data.get("reply_to_user_id")

    if not reply_to_msg_id or not reply_to_user_id:
        await state.clear()
        return

    reply_text = message.text or message.caption or ""

    try:
        # Отправляем ответ пользователю
        await bot.send_message(
            chat_id=reply_to_user_id,
            text=f"💬 <b>Ответ на ваше сообщение:</b>\n\n{reply_text}",
            parse_mode=ParseMode.HTML
        )

        # Сохраняем в БД
        await save_reply(reply_to_msg_id, reply_text)

        await message.answer(f"✅ Ответ отправлен!")

    except Exception as e:
        logger.error(f"Ошибка отправки ответа: {e}")
        await message.answer(f"❌ Не удалось отправить ответ: {e}")

    await state.clear()


# ============ ЗАПУСК ============

async def main():
    """Главная функция"""
    await init_db()

    logger.info("=" * 40)
    logger.info("🚀 Бот запущен!")
    logger.info(f"📢 Канал: {CHANNEL_ID}")
    logger.info(f"👑 Админы: {ADMIN_IDS}")
    logger.info("=" * 40)

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
