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
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
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
    get_user_history,
    get_user_stats,
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
    waiting_for_custom_reply = State()
    waiting_for_search = State()


# ============ КОНСТАНТЫ ============

CATEGORIES = {
    "question": "❓ Вопрос",
    "review": "💬 Отзыв",
    "idea": "💡 Идея",
    "thanks": "🙏 Благодарность",
    "problem": "⚠️ Проблема",
}

# Шаблоны быстрых ответов для БИМ радио
QUICK_REPLIES = {
    "thanks": "🎵 Спасибо за новость, люБИМка! Ты лучший(ая)!",
    "touched": "❤️ Ого, тронуло до глубины души! Спасибо, что поделился, люБИМка!",
    "on_air": "🎤 Обязательно передадим в эфир! Оставайся на волне БИМ!",
    "idea_good": "💡 Крутая идея, люБИМка! Возьмём на заметку!",
    "hug": "🤗 Обнимаем тебя через радиоволны! Спасибо, что ты с нами!",
}

# Ключевые слова для автокатегоризации
AUTO_CATEGORIES = {
    "question": ["как ", "почему", "зачем", "когда ", "где ", "кто ", "что ", "?", "подскажите", "помогите"],
    "idea": ["предлагаю", "идея", "можно было бы", "хорошо бы", "а если", "давайте"],
    "thanks": ["спасибо", "благодар", "молодцы", "класс", "круто", "супер", "лучшие", "люблю вас"],
    "problem": ["проблема", "не работает", "ошибка", "плохо", "ужас", "жалоба", "недовол"],
    "review": ["слушаю", "нравится", "эфир", "передача", "песня", "музыка", "ведущ"],
}

# Ключевые слова для приоритетов
PRIORITY_KEYWORDS = {
    "high": ["срочно", "важно", "помогите", "sos", "пожалуйста срочно", "критично", "немедленно"],
    "medium": ["вопрос", "когда", "подскажите", "ждём", "ожидаем"],
}


# ============ ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ============

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def detect_category(text: str) -> str | None:
    """Автоматически определить категорию по ключевым словам"""
    if not text:
        return None
    text_lower = text.lower()
    for category, keywords in AUTO_CATEGORIES.items():
        for keyword in keywords:
            if keyword in text_lower:
                return category
    return None


def detect_priority(text: str) -> str:
    """Определить приоритет сообщения"""
    if not text:
        return "normal"
    text_lower = text.lower()
    for priority, keywords in PRIORITY_KEYWORDS.items():
        for keyword in keywords:
            if keyword in text_lower:
                return priority
    return "normal"


def get_priority_emoji(priority: str) -> str:
    """Эмодзи приоритета"""
    return {"high": "🔴", "medium": "🟡", "normal": "🟢"}.get(priority, "🟢")


def format_wait_time(created_at) -> str:
    """Форматировать время ожидания ответа"""
    if isinstance(created_at, str):
        dt = datetime.fromisoformat(created_at)
    else:
        dt = created_at

    delta = datetime.now() - dt
    minutes = int(delta.total_seconds() / 60)
    hours = minutes // 60
    days = hours // 24

    if days > 0:
        return f"⏳ {days}д {hours % 24}ч"
    elif hours > 0:
        return f"⏳ {hours}ч {minutes % 60}мин"
    else:
        return f"⏳ {minutes}мин"


async def notify_admins_new_message(msg_id: int, user_name: str, text_preview: str, priority: str):
    """Push-уведомление админам о новом сообщении"""
    priority_emoji = get_priority_emoji(priority)
    preview = text_preview[:50] + "..." if len(text_preview) > 50 else text_preview

    notification = (
        f"{priority_emoji} <b>Новое сообщение #{msg_id}</b>\n"
        f"👤 {user_name}\n"
        f"💬 {preview or '[медиа]'}"
    )

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                chat_id=admin_id,
                text=notification,
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logger.warning(f"Не удалось уведомить админа {admin_id}: {e}")


def get_admin_reply_keyboard() -> ReplyKeyboardMarkup:
    """Постоянные кнопки внизу экрана для админов"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Статистика"), KeyboardButton(text="🆕 Непрочитанные")],
            [KeyboardButton(text="⭐ Избранные"), KeyboardButton(text="🔍 Поиск")],
            [KeyboardButton(text="📦 Экспорт"), KeyboardButton(text="🏷 Категории")],
        ],
        resize_keyboard=True,
        is_persistent=True
    )


def get_admin_menu_keyboard(stats: dict) -> InlineKeyboardMarkup:
    """Главное меню админа"""
    unread_count = stats.get('unread', 0)
    starred_count = stats.get('starred', 0)

    unread_text = f"🆕 Непрочитанные ({unread_count})" if unread_count > 0 else "🆕 Непрочитанные"

    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="menu:stats")],
        [
            InlineKeyboardButton(text=unread_text, callback_data="menu:unread"),
            InlineKeyboardButton(text=f"⭐ Избранные ({starred_count})", callback_data="menu:starred"),
        ],
        [
            InlineKeyboardButton(text="🔍 Поиск", callback_data="menu:search"),
            InlineKeyboardButton(text="📦 Экспорт", callback_data="menu:export"),
        ],
        [InlineKeyboardButton(text="🏷 По категориям", callback_data="menu:categories")],
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="menu:refresh")],
    ])


def get_categories_keyboard() -> InlineKeyboardMarkup:
    """Меню категорий"""
    buttons = []
    for key, name in CATEGORIES.items():
        buttons.append([InlineKeyboardButton(text=name, callback_data=f"showcat:{key}")])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="menu:back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_message_keyboard(message_db_id: int, is_starred: bool = False, show_nav: bool = False,
                         has_prev: bool = False, has_next: bool = False, list_type: str = "unread") -> InlineKeyboardMarkup:
    """Клавиатура для сообщения в канале"""
    star_emoji = "★" if is_starred else "☆"

    buttons = [
        # Ряд 1 - основные действия
        [
            InlineKeyboardButton(text=f"{star_emoji} Избранное", callback_data=f"star:{message_db_id}"),
            InlineKeyboardButton(text="💬 Ответить", callback_data=f"reply:{message_db_id}"),
            InlineKeyboardButton(text="🗑", callback_data=f"hide:{message_db_id}"),
        ],
        # Ряд 2 - категории
        [
            InlineKeyboardButton(text="❓", callback_data=f"cat:{message_db_id}:question"),
            InlineKeyboardButton(text="💬", callback_data=f"cat:{message_db_id}:review"),
            InlineKeyboardButton(text="💡", callback_data=f"cat:{message_db_id}:idea"),
            InlineKeyboardButton(text="🙏", callback_data=f"cat:{message_db_id}:thanks"),
            InlineKeyboardButton(text="⚠️", callback_data=f"cat:{message_db_id}:problem"),
        ],
        # Ряд 3 - прочитано
        [InlineKeyboardButton(text="✅ Прочитано", callback_data=f"read:{message_db_id}")],
    ]

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_quick_reply_keyboard(message_db_id: int) -> InlineKeyboardMarkup:
    """Клавиатура быстрых ответов для БИМ радио"""
    buttons = [
        [InlineKeyboardButton(text="🎵 Спасибо, люБИМка!", callback_data=f"qr:{message_db_id}:thanks")],
        [InlineKeyboardButton(text="❤️ Тронуло до глубины!", callback_data=f"qr:{message_db_id}:touched")],
        [InlineKeyboardButton(text="🎤 Передадим в эфир!", callback_data=f"qr:{message_db_id}:on_air")],
        [InlineKeyboardButton(text="💡 Крутая идея!", callback_data=f"qr:{message_db_id}:idea_good")],
        [InlineKeyboardButton(text="🤗 Обнимаем через радиоволны!", callback_data=f"qr:{message_db_id}:hug")],
        [InlineKeyboardButton(text="✏️ Свой текст...", callback_data=f"customreply:{message_db_id}")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancelreply")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_nav_keyboard(current_idx: int, total: int, list_type: str, message_db_id: int) -> InlineKeyboardMarkup:
    """Клавиатура навигации по списку сообщений"""
    buttons = []

    # Навигация
    nav_row = []
    if current_idx > 0:
        nav_row.append(InlineKeyboardButton(text="◀️ Пред.", callback_data=f"nav:{list_type}:{current_idx - 1}"))
    nav_row.append(InlineKeyboardButton(text=f"{current_idx + 1}/{total}", callback_data="noop"))
    if current_idx < total - 1:
        nav_row.append(InlineKeyboardButton(text="След. ▶️", callback_data=f"nav:{list_type}:{current_idx + 1}"))
    buttons.append(nav_row)

    # Действия с текущим
    buttons.append([
        InlineKeyboardButton(text="⭐", callback_data=f"navstar:{message_db_id}:{list_type}:{current_idx}"),
        InlineKeyboardButton(text="💬", callback_data=f"reply:{message_db_id}"),
        InlineKeyboardButton(text="✅", callback_data=f"navread:{message_db_id}:{list_type}:{current_idx}"),
        InlineKeyboardButton(text="🗑", callback_data=f"navhide:{message_db_id}:{list_type}:{current_idx}"),
    ])

    buttons.append([InlineKeyboardButton(text="◀️ В меню", callback_data="menu:back")])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def format_message_header(msg_id: int, user_id: int, username: str, full_name: str,
                          created_at, is_starred: bool = False, is_read: bool = False,
                          category: str = None, has_reply: bool = False) -> str:
    """Форматировать заголовок сообщения"""
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

    if username:
        user_link = f"@{username}"
    else:
        user_link = f"<a href='tg://user?id={user_id}'>{full_name}</a>"

    if isinstance(created_at, str):
        dt = datetime.fromisoformat(created_at)
    else:
        dt = created_at
    date_str = dt.strftime("%d.%m.%Y в %H:%M")

    header = f"{'━' * 20}\n"
    header += f"📩 <b>Сообщение #{msg_id}</b> {status_line}\n"
    header += f"👤 {user_link}\n"
    header += f"📝 {full_name}\n"
    header += f"🕐 {date_str}\n"
    header += f"{'━' * 20}\n\n"

    return header


def format_message_card(msg, show_text: bool = True) -> str:
    """Карточка сообщения для просмотра"""
    status = ""
    if msg["is_starred"]:
        status += "⭐ "
    if not msg["is_read"]:
        status += "🆕 "
    if msg["category"]:
        status += CATEGORIES.get(msg["category"], "").split()[0] + " "

    # Приоритет
    priority = detect_priority(msg["text"]) if msg["text"] else "normal"
    priority_emoji = get_priority_emoji(priority)

    username = f"@{msg['username']}" if msg['username'] else msg['full_name']

    if isinstance(msg["created_at"], str):
        dt = datetime.fromisoformat(msg["created_at"])
    else:
        dt = msg["created_at"]
    date_str = dt.strftime("%d.%m.%Y %H:%M")

    # Время ожидания (если нет ответа)
    wait_time = ""
    if not msg["reply_text"]:
        wait_time = " " + format_wait_time(msg["created_at"])

    text = f"{priority_emoji} <b>#{msg['id']}</b> {status}\n"
    text += f"👤 {username} ({msg['full_name']})\n"
    text += f"🕐 {date_str}{wait_time}\n"

    if show_text:
        content = msg["text"] or "[медиа]"
        if len(content) > 300:
            content = content[:300] + "..."
        text += f"\n{content}"

    if msg["reply_text"]:
        text += f"\n\n↩️ <i>Ответ: {msg['reply_text'][:100]}...</i>" if len(msg["reply_text"]) > 100 else f"\n\n↩️ <i>Ответ: {msg['reply_text']}</i>"

    return text


# ============ КОМАНДЫ ============

@dp.message(Command("start", "menu"))
async def cmd_start(message: Message, state: FSMContext):
    """Главное меню"""
    await state.clear()

    if is_admin(message.from_user.id):
        stats = await get_stats()

        text = (
            f"👋 <b>Панель управления</b>\n\n"
            f"📨 Всего сообщений: <b>{stats['total']}</b>\n"
            f"🆕 Непрочитанных: <b>{stats['unread']}</b>\n"
            f"⭐ Избранных: <b>{stats['starred']}</b>\n"
            f"👥 Пользователей: <b>{stats['unique_users']}</b>\n"
            f"📅 Сегодня: <b>{stats['today']}</b>\n"
        )

        # Показываем кнопки внизу экрана + inline меню
        await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=get_admin_reply_keyboard())
    else:
        await message.answer(
            "👋 <b>Привет!</b>\n\n"
            "Напиши мне своё сообщение, и оно будет передано автору.\n\n"
            "📝 Можешь отправить:\n"
            "• Текст\n"
            "• Фото\n"
            "• Голосовое\n"
            "• Видео\n"
            "• Документ\n\n"
            "✨ <i>Каждое сообщение важно!</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=ReplyKeyboardRemove()
        )


# ============ ОБРАБОТЧИКИ КНОПОК АДМИНА ============

@dp.message(F.text == "📊 Статистика")
async def btn_stats(message: Message):
    """Кнопка статистики"""
    if not is_admin(message.from_user.id):
        return

    stats = await get_stats()

    top_text = ""
    for i, (name, username, count) in enumerate(stats["top_users"], 1):
        medal = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"][i-1] if i <= 5 else f"{i}."
        user_display = f"@{username}" if username else name
        top_text += f"{medal} {user_display}: {count}\n"

    cat_text = ""
    for cat, count in stats["categories"].items():
        cat_text += f"• {CATEGORIES.get(cat, cat)}: {count}\n"
    if not cat_text:
        cat_text = "• <i>нет данных</i>\n"

    text = (
        f"📊 <b>СТАТИСТИКА</b>\n\n"
        f"<b>📨 Сообщения:</b>\n"
        f"• Всего: {stats['total']}\n"
        f"• Сегодня: {stats['today']}\n"
        f"• За неделю: {stats['week']}\n"
        f"• 🆕 Непрочитанных: {stats['unread']}\n"
        f"• ⭐ Избранных: {stats['starred']}\n"
        f"• ↩️ С ответами: {stats['replied']}\n\n"
        f"<b>👥 Пользователи:</b> {stats['unique_users']}\n\n"
        f"<b>🏆 Топ активных:</b>\n{top_text}\n"
        f"<b>🏷 По категориям:</b>\n{cat_text}"
    )

    await message.answer(text, parse_mode=ParseMode.HTML)


@dp.message(F.text == "🆕 Непрочитанные")
async def btn_unread(message: Message, state: FSMContext):
    """Кнопка непрочитанных"""
    if not is_admin(message.from_user.id):
        return

    messages = await get_unread_messages(limit=50)

    if not messages:
        await message.answer("✅ Всё прочитано!")
        return

    await state.update_data(message_list=[dict(m) for m in messages], list_type="unread")

    msg = messages[0]
    text = format_message_card(msg)
    keyboard = get_nav_keyboard(0, len(messages), "unread", msg["id"])

    await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)


@dp.message(F.text == "⭐ Избранные")
async def btn_starred(message: Message, state: FSMContext):
    """Кнопка избранных"""
    if not is_admin(message.from_user.id):
        return

    messages = await get_starred_messages(limit=50)

    if not messages:
        await message.answer("⭐ Избранных нет")
        return

    await state.update_data(message_list=[dict(m) for m in messages], list_type="starred")

    msg = messages[0]
    text = format_message_card(msg)
    keyboard = get_nav_keyboard(0, len(messages), "starred", msg["id"])

    await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)


@dp.message(F.text == "🔍 Поиск")
async def btn_search(message: Message, state: FSMContext):
    """Кнопка поиска"""
    if not is_admin(message.from_user.id):
        return

    await state.set_state(ReplyState.waiting_for_search)
    await message.answer("🔍 <b>Поиск</b>\n\nНапиши текст для поиска:", parse_mode=ParseMode.HTML)


@dp.message(F.text == "📦 Экспорт")
async def btn_export(message: Message):
    """Кнопка экспорта"""
    if not is_admin(message.from_user.id):
        return

    await message.answer("📦 Готовлю экспорт...")

    messages = await export_messages()

    if not messages:
        await message.answer("📭 Нет сообщений")
        return

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

    filename = f"export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(export_data, f, ensure_ascii=False, indent=2)

    await message.answer_document(
        FSInputFile(filename),
        caption=f"📦 Экспорт: {len(export_data)} сообщений"
    )

    import os
    os.remove(filename)


@dp.message(F.text == "🏷 Категории")
async def btn_categories(message: Message):
    """Кнопка категорий"""
    if not is_admin(message.from_user.id):
        return

    await message.answer(
        "🏷 <b>Категории</b>\n\nВыбери категорию:",
        parse_mode=ParseMode.HTML,
        reply_markup=get_categories_keyboard()
    )


@dp.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    """Отмена"""
    await state.clear()
    await message.answer("❌ Отменено")


# ============ CALLBACK: МЕНЮ ============

@dp.callback_query(F.data == "menu:back")
@dp.callback_query(F.data == "menu:refresh")
async def callback_menu_back(callback: CallbackQuery, state: FSMContext):
    """Вернуться в главное меню"""
    await state.clear()

    if not is_admin(callback.from_user.id):
        await callback.answer("⛔️ Только для админов")
        return

    stats = await get_stats()

    text = (
        f"👋 <b>Панель управления</b>\n\n"
        f"📨 Всего сообщений: <b>{stats['total']}</b>\n"
        f"🆕 Непрочитанных: <b>{stats['unread']}</b>\n"
        f"⭐ Избранных: <b>{stats['starred']}</b>\n"
        f"👥 Пользователей: <b>{stats['unique_users']}</b>\n"
        f"📅 Сегодня: <b>{stats['today']}</b>\n"
    )

    try:
        await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=get_admin_menu_keyboard(stats))
    except:
        await callback.message.answer(text, parse_mode=ParseMode.HTML, reply_markup=get_admin_menu_keyboard(stats))

    await callback.answer()


@dp.callback_query(F.data == "menu:stats")
async def callback_menu_stats(callback: CallbackQuery):
    """Показать статистику"""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔️")
        return

    stats = await get_stats()

    # Топ пользователей
    top_text = ""
    for i, (name, username, count) in enumerate(stats["top_users"], 1):
        medal = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"][i-1] if i <= 5 else f"{i}."
        user_display = f"@{username}" if username else name
        top_text += f"{medal} {user_display}: {count}\n"

    # Категории
    cat_text = ""
    for cat, count in stats["categories"].items():
        cat_text += f"• {CATEGORIES.get(cat, cat)}: {count}\n"
    if not cat_text:
        cat_text = "• <i>нет данных</i>\n"

    text = (
        f"📊 <b>СТАТИСТИКА</b>\n\n"
        f"<b>📨 Сообщения:</b>\n"
        f"• Всего: {stats['total']}\n"
        f"• Сегодня: {stats['today']}\n"
        f"• За неделю: {stats['week']}\n"
        f"• 🆕 Непрочитанных: {stats['unread']}\n"
        f"• ⭐ Избранных: {stats['starred']}\n"
        f"• ↩️ С ответами: {stats['replied']}\n\n"
        f"<b>👥 Пользователи:</b> {stats['unique_users']}\n\n"
        f"<b>🏆 Топ активных:</b>\n{top_text}\n"
        f"<b>🏷 По категориям:</b>\n{cat_text}"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu:back")]
    ])

    await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
    await callback.answer()


@dp.callback_query(F.data == "menu:unread")
async def callback_menu_unread(callback: CallbackQuery, state: FSMContext):
    """Показать непрочитанные"""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔️")
        return

    messages = await get_unread_messages(limit=50)

    if not messages:
        await callback.answer("✅ Всё прочитано!")
        return

    # Сохраняем список в state для навигации
    await state.update_data(message_list=[dict(m) for m in messages], list_type="unread")

    msg = messages[0]
    text = format_message_card(msg)
    keyboard = get_nav_keyboard(0, len(messages), "unread", msg["id"])

    await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
    await callback.answer()


@dp.callback_query(F.data == "menu:starred")
async def callback_menu_starred(callback: CallbackQuery, state: FSMContext):
    """Показать избранные"""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔️")
        return

    messages = await get_starred_messages(limit=50)

    if not messages:
        await callback.answer("⭐ Избранных нет")
        return

    await state.update_data(message_list=[dict(m) for m in messages], list_type="starred")

    msg = messages[0]
    text = format_message_card(msg)
    keyboard = get_nav_keyboard(0, len(messages), "starred", msg["id"])

    await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
    await callback.answer()


@dp.callback_query(F.data == "menu:search")
async def callback_menu_search(callback: CallbackQuery, state: FSMContext):
    """Начать поиск"""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔️")
        return

    await state.set_state(ReplyState.waiting_for_search)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="menu:back")]
    ])

    await callback.message.edit_text(
        "🔍 <b>Поиск по сообщениям</b>\n\n"
        "Напиши текст для поиска:",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard
    )
    await callback.answer()


@dp.callback_query(F.data == "menu:export")
async def callback_menu_export(callback: CallbackQuery):
    """Экспорт"""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔️")
        return

    await callback.answer("📦 Готовлю экспорт...")

    messages = await export_messages()

    if not messages:
        await callback.message.answer("📭 Нет сообщений")
        return

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

    filename = f"export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(export_data, f, ensure_ascii=False, indent=2)

    await callback.message.answer_document(
        FSInputFile(filename),
        caption=f"📦 Экспорт: {len(export_data)} сообщений"
    )

    import os
    os.remove(filename)


@dp.callback_query(F.data == "menu:categories")
async def callback_menu_categories(callback: CallbackQuery):
    """Меню категорий"""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔️")
        return

    await callback.message.edit_text(
        "🏷 <b>Категории</b>\n\nВыбери категорию:",
        parse_mode=ParseMode.HTML,
        reply_markup=get_categories_keyboard()
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("showcat:"))
async def callback_show_category(callback: CallbackQuery, state: FSMContext):
    """Показать сообщения категории"""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔️")
        return

    category = callback.data.split(":")[1]
    messages = await get_messages_by_category(category, limit=50)

    if not messages:
        await callback.answer(f"В категории {CATEGORIES[category]} пусто")
        return

    await state.update_data(message_list=[dict(m) for m in messages], list_type=f"cat_{category}")

    msg = messages[0]
    text = format_message_card(msg)
    keyboard = get_nav_keyboard(0, len(messages), f"cat_{category}", msg["id"])

    await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
    await callback.answer()


# ============ CALLBACK: НАВИГАЦИЯ ============

@dp.callback_query(F.data.startswith("nav:"))
async def callback_nav(callback: CallbackQuery, state: FSMContext):
    """Навигация по списку"""
    parts = callback.data.split(":")
    list_type = parts[1]
    idx = int(parts[2])

    data = await state.get_data()
    messages = data.get("message_list", [])

    if not messages or idx >= len(messages):
        await callback.answer("Список обновился, начни заново")
        return

    msg = messages[idx]
    text = format_message_card(msg)
    keyboard = get_nav_keyboard(idx, len(messages), list_type, msg["id"])

    await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
    await callback.answer()


@dp.callback_query(F.data.startswith("navstar:"))
async def callback_nav_star(callback: CallbackQuery, state: FSMContext):
    """Избранное из навигации"""
    parts = callback.data.split(":")
    msg_id = int(parts[1])
    list_type = parts[2]
    idx = int(parts[3])

    new_status = await toggle_starred(msg_id)

    # Обновляем в state
    data = await state.get_data()
    messages = data.get("message_list", [])
    if idx < len(messages):
        messages[idx]["is_starred"] = int(new_status)
        await state.update_data(message_list=messages)

    msg = messages[idx]
    text = format_message_card(msg)
    keyboard = get_nav_keyboard(idx, len(messages), list_type, msg["id"])

    await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
    await callback.answer("⭐" if new_status else "Убрано из избранного")


@dp.callback_query(F.data.startswith("navread:"))
async def callback_nav_read(callback: CallbackQuery, state: FSMContext):
    """Прочитано из навигации"""
    parts = callback.data.split(":")
    msg_id = int(parts[1])
    list_type = parts[2]
    idx = int(parts[3])

    await mark_as_read(msg_id)

    data = await state.get_data()
    messages = data.get("message_list", [])
    if idx < len(messages):
        messages[idx]["is_read"] = 1
        await state.update_data(message_list=messages)

    msg = messages[idx]
    text = format_message_card(msg)
    keyboard = get_nav_keyboard(idx, len(messages), list_type, msg["id"])

    await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
    await callback.answer("✅ Прочитано")


@dp.callback_query(F.data.startswith("navhide:"))
async def callback_nav_hide(callback: CallbackQuery, state: FSMContext):
    """Скрыть из навигации"""
    parts = callback.data.split(":")
    msg_id = int(parts[1])
    list_type = parts[2]
    idx = int(parts[3])

    await toggle_hidden(msg_id)

    data = await state.get_data()
    messages = data.get("message_list", [])

    # Удаляем из списка
    if idx < len(messages):
        messages.pop(idx)
        await state.update_data(message_list=messages)

    if not messages:
        await callback.answer("🗑 Скрыто. Список пуст.")
        # Возврат в меню
        stats = await get_stats()
        text = f"👋 <b>Панель управления</b>\n\n📨 Сообщений: <b>{stats['total']}</b>"
        await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=get_admin_menu_keyboard(stats))
        return

    # Показываем следующее или предыдущее
    new_idx = min(idx, len(messages) - 1)
    msg = messages[new_idx]
    text = format_message_card(msg)
    keyboard = get_nav_keyboard(new_idx, len(messages), list_type, msg["id"])

    await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
    await callback.answer("🗑 Скрыто")


@dp.callback_query(F.data == "noop")
async def callback_noop(callback: CallbackQuery):
    await callback.answer()


# ============ CALLBACK: ДЕЙСТВИЯ С СООБЩЕНИЯМИ ============

@dp.callback_query(F.data.startswith("star:"))
async def callback_star(callback: CallbackQuery):
    """Избранное"""
    msg_id = int(callback.data.split(":")[1])
    new_status = await toggle_starred(msg_id)

    msg = await get_message_by_id(msg_id)
    keyboard = get_message_keyboard(msg_id, is_starred=new_status)

    try:
        await callback.message.edit_reply_markup(reply_markup=keyboard)
    except:
        pass

    await callback.answer("⭐ Избранное" if new_status else "Убрано")


@dp.callback_query(F.data.startswith("hide:"))
async def callback_hide(callback: CallbackQuery):
    """Скрыть"""
    msg_id = int(callback.data.split(":")[1])
    await toggle_hidden(msg_id)

    try:
        await callback.message.delete()
    except:
        pass

    await callback.answer("🗑 Скрыто")


@dp.callback_query(F.data.startswith("read:"))
async def callback_read(callback: CallbackQuery):
    """Прочитано"""
    msg_id = int(callback.data.split(":")[1])
    await mark_as_read(msg_id)

    msg = await get_message_by_id(msg_id)
    keyboard = get_message_keyboard(msg_id, is_starred=bool(msg["is_starred"]) if msg else False)

    try:
        await callback.message.edit_reply_markup(reply_markup=keyboard)
    except:
        pass

    await callback.answer("✅ Прочитано")


@dp.callback_query(F.data.startswith("cat:"))
async def callback_category(callback: CallbackQuery):
    """Категория"""
    parts = callback.data.split(":")
    msg_id = int(parts[1])
    category = parts[2]

    await set_category(msg_id, category)

    msg = await get_message_by_id(msg_id)
    keyboard = get_message_keyboard(msg_id, is_starred=bool(msg["is_starred"]) if msg else False)

    try:
        await callback.message.edit_reply_markup(reply_markup=keyboard)
    except:
        pass

    await callback.answer(f"🏷 {CATEGORIES.get(category, category)}")


# ============ CALLBACK: ОТВЕТЫ ============

@dp.callback_query(F.data.startswith("reply:"))
async def callback_reply(callback: CallbackQuery, state: FSMContext):
    """Начать ответ - показать быстрые ответы и историю пользователя"""
    msg_id = int(callback.data.split(":")[1])
    msg = await get_message_by_id(msg_id)

    if not msg:
        await callback.answer("❌ Не найдено")
        return

    await state.update_data(reply_to_msg_id=msg_id, reply_to_user_id=msg["user_id"])

    # Получаем историю пользователя
    user_stats = await get_user_stats(msg["user_id"])
    user_history = await get_user_history(msg["user_id"], limit=3)

    # Формируем историю
    history_text = ""
    if user_stats["total"] > 1:
        history_text = f"\n\n📊 <b>История люБИМки:</b>\n"
        history_text += f"• Всего сообщений: {user_stats['total']}\n"
        history_text += f"• Ответов получено: {user_stats['replied']}\n"

        if len(user_history) > 1:
            history_text += "\n<i>Последние сообщения:</i>\n"
            for h in user_history[1:]:  # Пропускаем текущее
                preview = (h["text"] or "[медиа]")[:40]
                if len(h["text"] or "") > 40:
                    preview += "..."
                history_text += f"• {preview}\n"

    await callback.message.answer(
        f"💬 <b>Ответ на #{msg_id}</b>\n"
        f"От: {msg['full_name']}"
        f"{history_text}\n\n"
        f"Выбери быстрый ответ или напиши свой:",
        parse_mode=ParseMode.HTML,
        reply_markup=get_quick_reply_keyboard(msg_id)
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("qr:"))
async def callback_quick_reply(callback: CallbackQuery, state: FSMContext):
    """Быстрый ответ"""
    parts = callback.data.split(":")
    msg_id = int(parts[1])
    reply_key = parts[2]

    reply_text = QUICK_REPLIES.get(reply_key, "Спасибо за сообщение!")

    data = await state.get_data()
    user_id = data.get("reply_to_user_id")

    if not user_id:
        msg = await get_message_by_id(msg_id)
        user_id = msg["user_id"] if msg else None

    if not user_id:
        await callback.answer("❌ Ошибка")
        return

    try:
        await bot.send_message(
            chat_id=user_id,
            text=f"💬 <b>Ответ на ваше сообщение:</b>\n\n{reply_text}",
            parse_mode=ParseMode.HTML
        )
        await save_reply(msg_id, reply_text)
        await callback.message.edit_text("✅ Ответ отправлен!")
    except Exception as e:
        await callback.message.edit_text(f"❌ Ошибка: {e}")

    await state.clear()
    await callback.answer()


@dp.callback_query(F.data.startswith("customreply:"))
async def callback_custom_reply(callback: CallbackQuery, state: FSMContext):
    """Свой текст ответа"""
    msg_id = int(callback.data.split(":")[1])

    await state.update_data(reply_to_msg_id=msg_id)
    await state.set_state(ReplyState.waiting_for_custom_reply)

    await callback.message.edit_text(
        "✏️ Напиши свой ответ:\n\n"
        "<i>Или /cancel для отмены</i>",
        parse_mode=ParseMode.HTML
    )
    await callback.answer()


@dp.callback_query(F.data == "cancelreply")
async def callback_cancel_reply(callback: CallbackQuery, state: FSMContext):
    """Отмена ответа"""
    await state.clear()
    await callback.message.delete()
    await callback.answer("Отменено")


# ============ ОБРАБОТКА СООБЩЕНИЙ ============

@dp.message(ReplyState.waiting_for_search)
async def handle_search(message: Message, state: FSMContext):
    """Обработка поиска"""
    query = message.text

    messages = await search_messages(query, limit=50)

    if not messages:
        await message.answer(f"🔍 По запросу «{query}» ничего не найдено")
        await state.clear()
        return

    await state.update_data(message_list=[dict(m) for m in messages], list_type="search")
    await state.set_state(None)

    msg = messages[0]
    text = f"🔍 <b>Результаты: «{query}»</b> ({len(messages)})\n\n"
    text += format_message_card(msg)
    keyboard = get_nav_keyboard(0, len(messages), "search", msg["id"])

    await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)


@dp.message(ReplyState.waiting_for_custom_reply)
async def handle_custom_reply(message: Message, state: FSMContext):
    """Обработка своего ответа"""
    data = await state.get_data()
    msg_id = data.get("reply_to_msg_id")
    user_id = data.get("reply_to_user_id")

    if not msg_id:
        await state.clear()
        return

    if not user_id:
        msg = await get_message_by_id(msg_id)
        user_id = msg["user_id"] if msg else None

    reply_text = message.text

    try:
        await bot.send_message(
            chat_id=user_id,
            text=f"💬 <b>Ответ на ваше сообщение:</b>\n\n{reply_text}",
            parse_mode=ParseMode.HTML
        )
        await save_reply(msg_id, reply_text)
        await message.answer("✅ Ответ отправлен!")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

    await state.clear()


@dp.message(F.text | F.photo | F.voice | F.video | F.video_note | F.document)
async def handle_user_message(message: Message, state: FSMContext):
    """Сообщения от пользователей"""

    # Проверяем состояние
    current_state = await state.get_state()
    if current_state:
        return

    # Админы не пересылаются
    if is_admin(message.from_user.id):
        return

    user = message.from_user
    username = user.username or ""
    full_name = user.full_name or "Без имени"

    has_photo = bool(message.photo)
    has_voice = bool(message.voice)
    has_video = bool(message.video or message.video_note)
    text_content = message.text or message.caption or ""

    # Автоопределение категории и приоритета
    auto_category = detect_category(text_content)
    priority = detect_priority(text_content)
    priority_emoji = get_priority_emoji(priority)

    try:
        # Сохраняем
        msg_id = await save_message(
            telegram_message_id=message.message_id,
            channel_message_id=0,
            user_id=user.id,
            username=username,
            full_name=full_name,
            text=text_content,
            has_photo=has_photo,
            has_voice=has_voice,
            has_video=has_video
        )

        # Устанавливаем автокатегорию если определена
        if auto_category:
            await set_category(msg_id, auto_category)

        # Добавляем приоритет в заголовок
        priority_line = ""
        if priority != "normal":
            priority_line = f"\n{priority_emoji} <b>{'СРОЧНО!' if priority == 'high' else 'Требует внимания'}</b>"

        category_line = ""
        if auto_category:
            category_line = f"\n🏷 {CATEGORIES.get(auto_category, auto_category)}"

        header = format_message_header(
            msg_id=msg_id,
            user_id=user.id,
            username=username,
            full_name=full_name,
            created_at=datetime.now()
        )
        header = header.rstrip() + priority_line + category_line + "\n\n"

        keyboard = get_message_keyboard(msg_id)

        # Отправляем в канал
        if message.photo:
            await bot.send_photo(
                chat_id=CHANNEL_ID,
                photo=message.photo[-1].file_id,
                caption=f"{header}{text_content}",
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard
            )
        elif message.voice:
            await bot.send_voice(
                chat_id=CHANNEL_ID,
                voice=message.voice.file_id,
                caption=header,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard
            )
        elif message.video:
            await bot.send_video(
                chat_id=CHANNEL_ID,
                video=message.video.file_id,
                caption=f"{header}{text_content}",
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard
            )
        elif message.video_note:
            await bot.send_message(chat_id=CHANNEL_ID, text=header, parse_mode=ParseMode.HTML)
            await bot.send_video_note(chat_id=CHANNEL_ID, video_note=message.video_note.file_id)
        elif message.document:
            await bot.send_document(
                chat_id=CHANNEL_ID,
                document=message.document.file_id,
                caption=f"{header}{text_content}",
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard
            )
        else:
            await bot.send_message(
                chat_id=CHANNEL_ID,
                text=f"{header}{text_content}",
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard
            )

        # Push-уведомления админам
        await notify_admins_new_message(msg_id, full_name, text_content, priority)

        await message.answer(AUTO_REPLY_TEXT)
        logger.info(f"#{msg_id} от {full_name} [{priority}]")

    except Exception as e:
        logger.error(f"Ошибка: {e}")
        await message.answer("❌ Ошибка. Попробуйте позже.")


# ============ ЗАПУСК ============

async def main():
    await init_db()
    logger.info("=" * 40)
    logger.info("🚀 Бот запущен!")
    logger.info(f"📢 Канал: {CHANNEL_ID}")
    logger.info(f"👑 Админы: {ADMIN_IDS}")
    logger.info("=" * 40)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
