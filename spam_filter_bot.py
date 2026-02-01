"""
Спам-фильтр бот для Telegram чатов
- Верификация новых участников кнопкой
- Фильтрация спама по ключевым словам
- Автоудаление/бан спамеров
"""

import asyncio
import re
import logging
from datetime import datetime, timedelta
from typing import Dict, Set

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    Message, CallbackQuery, ChatPermissions,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ChatMemberUpdated
)
from aiogram.filters import ChatMemberUpdatedFilter, IS_NOT_MEMBER, IS_MEMBER, Command
from aiogram.enums import ChatMemberStatus
from dotenv import load_dotenv
import os

load_dotenv()

# ============== НАСТРОЙКИ ==============
BOT_TOKEN = os.getenv("SPAM_BOT_TOKEN")
ADMIN_IDS = [int(x.strip()) for x in os.getenv("SPAM_ADMIN_IDS", "").split(",") if x.strip()]

# Время на верификацию (секунды)
VERIFY_TIMEOUT = 60

# ============== СТОП-СЛОВА ==============
SPAM_KEYWORDS = [
    # Работа/Заработок
    "заработок", "заработай", "заработать", "зарабатывай", "зарабатывать",
    "пассивный доход", "легкий заработок", "быстрый заработок",
    "удаленная работа", "работа на дому", "подработка",
    "пиши в лс", "напиши в личку", "в лс", "пиши в личку",
    "без опыта", "без вложений", "гарантированный доход",
    "доход от", "зарплата от", "от 100к", "от 90000", "от 50000",
    "лайки за деньги", "клики за деньги", "просмотры за деньги",
    "обучение платное", "вводный курс",
    "требуются сотрудники", "набираем людей", "ищем сотрудников",

    # Крипта/Инвестиции
    "крипта", "криптовалюта", "биткоин", "эфир", "тонкоин",
    "инвестиции", "инвестируй", "вложи деньги",
    "трейдинг", "торговый бот", "торговые сигналы",
    "майнинг", "облачный майнинг",
    "airdrop", "аирдроп", "пампим", "памп",
    "p2p заработок", "арбитраж крипты",

    # Фишинг 2025-2026
    "итоги года", "твой 2025", "твой 2026",
    "premium бесплатно", "подписка в подарок",
    "проголосуй за", "голосование за ребенка",
    "ваш аккаунт взломан", "подтвердите аккаунт",

    # Казино/Ставки
    "казино", "ставки на спорт", "букмекер",
    "1xbet", "1win", "мелбет", "fonbet",
    "слоты", "рулетка", "покер онлайн",
    "выигрыш", "джекпот", "промокод",

    # 18+
    "интим", "эскорт", "массаж для мужчин",
    "знакомства 18", "девушки на час",

    # Общий спам
    "дам денег", "раздаю деньги",
    "халява", "бесплатно раздаю",
    "срочно!!!", "только сегодня",
    "последний шанс", "эксклюзивное предложение",
    "переходи по ссылке", "жми на ссылку",
    "подписывайся на канал",
]

# Корни слов для частичного поиска
SPAM_ROOTS = [
    "заработ", "зарабат", "зароботок",
    "крипт", "инвест", "трейдинг",
    "казин", "ставк",
]

# Подозрительные паттерны
SPAM_PATTERNS = [
    r"(?:от|до)\s*\d{2,3}\s*(?:к|тыс|000)",  # от 50к, до 100 тыс
    r"\d{5,}\s*(?:₽|руб|рублей|р\.)",  # 50000 рублей
    r"(?:пиш[иу]|напиш[иу])\s*(?:в\s*)?(?:лс|личк|дм|dm)",  # пиши в лс
    r"t\.me/[a-zA-Z0-9_]+",  # ссылки на телеграм
    r"bit\.ly/",  # короткие ссылки
    r"@[a-zA-Z0-9_]{5,}",  # упоминания ботов/каналов
]

# ============== ЛОГИРОВАНИЕ ==============
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============== БОТ ==============
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()

# Хранилище ожидающих верификации: {user_id: {"chat_id": ..., "message_id": ..., "task": ...}}
pending_verification: Dict[int, dict] = {}

# Верифицированные пользователи (чтобы не проверять повторно)
verified_users: Set[int] = set()

# Статистика
stats = {
    "spam_deleted": 0,
    "users_verified": 0,
    "users_kicked": 0,
    "start_time": datetime.now()
}


def normalize_text(text: str) -> str:
    """Нормализация текста для поиска спама"""
    text = text.lower()
    # Замена латинских букв на кириллицу (антиобход)
    replacements = {
        'a': 'а', 'e': 'е', 'o': 'о', 'p': 'р', 'c': 'с',
        'x': 'х', 'y': 'у', 'k': 'к', 'h': 'н', 'm': 'м',
        'b': 'в', 't': 'т'
    }
    for lat, cyr in replacements.items():
        text = text.replace(lat, cyr)
    # Удаление лишних пробелов и спецсимволов
    text = re.sub(r'[^\w\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def is_spam(text: str) -> tuple[bool, str]:
    """Проверка сообщения на спам"""
    if not text:
        return False, ""

    normalized = normalize_text(text)
    original_lower = text.lower()

    # Проверка по ключевым словам
    for keyword in SPAM_KEYWORDS:
        if keyword in normalized:
            return True, f"ключевое слово: {keyword}"

    # Проверка по корням слов
    for root in SPAM_ROOTS:
        if root in normalized:
            return True, f"корень слова: {root}"

    # Проверка по паттернам
    for pattern in SPAM_PATTERNS:
        if re.search(pattern, original_lower):
            return True, f"паттерн: {pattern[:30]}..."

    # Проверка на избыток эмодзи (больше 7)
    emoji_count = len(re.findall(r'[\U0001F300-\U0001F9FF]', text))
    if emoji_count > 7:
        return True, f"много эмодзи: {emoji_count}"

    return False, ""


def get_verify_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Клавиатура для верификации"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="✅ Я не робот",
            callback_data=f"verify_{user_id}"
        )]
    ])


async def kick_unverified(user_id: int, chat_id: int, message_id: int):
    """Кик пользователя, не прошедшего верификацию"""
    await asyncio.sleep(VERIFY_TIMEOUT)

    if user_id in pending_verification:
        try:
            # Удаляем сообщение с кнопкой
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
            # Кикаем пользователя
            await bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
            await asyncio.sleep(1)
            # Разбаниваем чтобы мог зайти снова
            await bot.unban_chat_member(chat_id=chat_id, user_id=user_id)

            stats["users_kicked"] += 1
            logger.info(f"Kicked unverified user {user_id} from {chat_id}")
        except Exception as e:
            logger.error(f"Error kicking user {user_id}: {e}")
        finally:
            pending_verification.pop(user_id, None)


# ============== ОБРАБОТЧИКИ ==============

@router.chat_member(ChatMemberUpdatedFilter(IS_NOT_MEMBER >> IS_MEMBER))
async def on_user_join(event: ChatMemberUpdated):
    """Новый участник присоединился"""
    user = event.new_chat_member.user
    chat_id = event.chat.id

    # Пропускаем ботов и админов
    if user.is_bot:
        return
    if user.id in ADMIN_IDS:
        verified_users.add(user.id)
        return

    # Если уже верифицирован ранее
    if user.id in verified_users:
        return

    try:
        # Ограничиваем права (мьют)
        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user.id,
            permissions=ChatPermissions(
                can_send_messages=False,
                can_send_media_messages=False,
                can_send_other_messages=False,
                can_add_web_page_previews=False
            )
        )

        # Отправляем сообщение с кнопкой верификации
        user_name = user.full_name or user.username or "Пользователь"
        msg = await bot.send_message(
            chat_id=chat_id,
            text=(
                f"👋 <b>Добро пожаловать, {user_name}!</b>\n\n"
                f"🔒 Для защиты от спама нажмите кнопку ниже "
                f"в течение {VERIFY_TIMEOUT} секунд.\n\n"
                f"Иначе вы будете удалены из чата."
            ),
            reply_markup=get_verify_keyboard(user.id),
            parse_mode="HTML"
        )

        # Запускаем таймер на кик
        task = asyncio.create_task(kick_unverified(user.id, chat_id, msg.message_id))

        pending_verification[user.id] = {
            "chat_id": chat_id,
            "message_id": msg.message_id,
            "task": task
        }

        logger.info(f"User {user.id} ({user_name}) joined, waiting for verification")

    except Exception as e:
        logger.error(f"Error handling new member {user.id}: {e}")


@router.callback_query(F.data.startswith("verify_"))
async def on_verify_click(callback: CallbackQuery):
    """Пользователь нажал кнопку верификации"""
    user_id = int(callback.data.split("_")[1])

    # Проверяем, что кнопку нажал тот, кому она предназначена
    if callback.from_user.id != user_id:
        await callback.answer("❌ Эта кнопка не для вас!", show_alert=True)
        return

    chat_id = callback.message.chat.id

    try:
        # Отменяем таймер кика
        if user_id in pending_verification:
            pending_verification[user_id]["task"].cancel()
            pending_verification.pop(user_id, None)

        # Снимаем ограничения
        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=ChatPermissions(
                can_send_messages=True,
                can_send_media_messages=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
                can_send_polls=True,
                can_invite_users=True,
                can_change_info=False,
                can_pin_messages=False
            )
        )

        # Добавляем в верифицированные
        verified_users.add(user_id)
        stats["users_verified"] += 1

        # Обновляем сообщение
        await callback.message.edit_text(
            f"✅ <b>{callback.from_user.full_name}</b> верифицирован!\n\n"
            f"Добро пожаловать в чат! 🎉",
            parse_mode="HTML"
        )

        # Удаляем сообщение через 5 секунд
        await asyncio.sleep(5)
        try:
            await callback.message.delete()
        except:
            pass

        logger.info(f"User {user_id} verified successfully")

    except Exception as e:
        logger.error(f"Error verifying user {user_id}: {e}")
        await callback.answer("Ошибка верификации", show_alert=True)


@router.message(F.chat.type.in_({"group", "supergroup"}))
async def on_group_message(message: Message):
    """Проверка сообщений на спам"""
    # Пропускаем админов
    if message.from_user.id in ADMIN_IDS:
        return

    # Пропускаем команды
    if message.text and message.text.startswith("/"):
        return

    # Получаем текст
    text = message.text or message.caption or ""

    # Проверяем на спам
    spam_detected, reason = is_spam(text)

    if spam_detected:
        try:
            # Удаляем сообщение
            await message.delete()
            stats["spam_deleted"] += 1

            user_name = message.from_user.full_name or message.from_user.username
            logger.info(f"Spam deleted from {user_name} ({message.from_user.id}): {reason}")

            # Уведомление (удалится через 5 секунд)
            warn_msg = await message.answer(
                f"🚫 Сообщение от <b>{user_name}</b> удалено.\n"
                f"Причина: {reason}",
                parse_mode="HTML"
            )
            await asyncio.sleep(5)
            try:
                await warn_msg.delete()
            except:
                pass

        except Exception as e:
            logger.error(f"Error deleting spam: {e}")


@router.message(Command("spam_stats"))
async def cmd_stats(message: Message):
    """Статистика бота (только для админов)"""
    if message.from_user.id not in ADMIN_IDS:
        return

    uptime = datetime.now() - stats["start_time"]
    hours = int(uptime.total_seconds() // 3600)
    minutes = int((uptime.total_seconds() % 3600) // 60)

    await message.answer(
        f"📊 <b>Статистика спам-фильтра</b>\n\n"
        f"⏱ Аптайм: {hours}ч {minutes}м\n"
        f"🗑 Удалено спама: {stats['spam_deleted']}\n"
        f"✅ Верифицировано: {stats['users_verified']}\n"
        f"🚫 Кикнуто: {stats['users_kicked']}\n"
        f"👥 В базе верифиц.: {len(verified_users)}",
        parse_mode="HTML"
    )


@router.message(Command("spam_add"))
async def cmd_add_keyword(message: Message):
    """Добавить ключевое слово (только для админов)"""
    if message.from_user.id not in ADMIN_IDS:
        return

    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Использование: /spam_add <слово или фраза>")
        return

    keyword = args[1].lower().strip()
    if keyword not in SPAM_KEYWORDS:
        SPAM_KEYWORDS.append(keyword)
        await message.answer(f"✅ Добавлено: <code>{keyword}</code>", parse_mode="HTML")
    else:
        await message.answer(f"⚠️ Уже есть: <code>{keyword}</code>", parse_mode="HTML")


@router.message(Command("spam_help"))
async def cmd_help(message: Message):
    """Помощь по командам"""
    if message.from_user.id not in ADMIN_IDS:
        return

    await message.answer(
        "🤖 <b>Команды спам-фильтра</b>\n\n"
        "/spam_stats — статистика бота\n"
        "/spam_add <слово> — добавить стоп-слово\n"
        "/spam_help — эта справка",
        parse_mode="HTML"
    )


async def main():
    """Запуск бота"""
    logger.info("Starting spam filter bot...")

    dp.include_router(router)

    # Удаляем вебхук если был
    await bot.delete_webhook(drop_pending_updates=True)

    logger.info("Bot started successfully!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
