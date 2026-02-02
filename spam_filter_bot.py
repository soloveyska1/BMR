"""
Спам-фильтр бот для Telegram чатов v2.0
- Верификация новых участников кнопкой
- Умная фильтрация спама (ключевые слова + паттерны + комбинации)
- Детекция удалённых аккаунтов и подозрительных профилей
- Обнаружение дубликатов сообщений
- Анализ поведения пользователей
"""

import asyncio
import re
import logging
import hashlib
from datetime import datetime, timedelta
from typing import Dict, Set, List, Tuple
from collections import defaultdict
from dataclasses import dataclass, field

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    Message, CallbackQuery, ChatPermissions,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ChatMemberUpdated, User
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
    # Работа/Заработок (расширенный)
    "заработок", "заработай", "заработать", "зарабатывай", "зарабатывать",
    "пассивный доход", "легкий заработок", "быстрый заработок",
    "удаленная работа", "работа на дому",
    "без опыта", "без вложений", "гарантированный доход",
    "доход от", "зарплата от", "от 100к", "от 90000", "от 50000",
    "лайки за деньги", "клики за деньги", "просмотры за деньги",
    "обучение платное", "вводный курс",
    "требуются сотрудники", "набираем людей", "ищем сотрудников",
    "требуются на завтра", "требуются на сегодня", "нужны люди",
    "оплата сразу", "оплата ежедневно", "оплата в тот же день",
    "высокий доход", "хороший доход", "стабильный доход",
    "дополнительный доход", "дополнительный заработок",
    "работа для всех", "работа для каждого",
    "не упусти", "не упустите", "успей", "успейте",

    # НОВОЕ: Скрытый спам работы (как на скриншотах)
    "связь через личку", "уточнения в лс", "подробности в лс",
    "детали в лс", "информация в лс", "условия в лс",
    "лёгкая работа", "легкая работа", "несложная работа",
    "небольшие поручения", "мелкие поручения", "простые поручения",
    "небольшие задания", "простые задания",
    "ищу специалист", "ищу помощник", "нужен помощник",
    "предлагается работа", "предлагаю работу",
    "опыт в домашних делах", "домашние дела",
    "внимательность важна", "ответственность важна",
    "удобное расписание", "свободный график", "гибкий график",

    # Крипта/Инвестиции
    "крипта", "криптовалюта", "биткоин", "эфир", "тонкоин",
    "инвестиции", "инвестируй", "вложи деньги",
    "трейдинг", "торговый бот", "торговые сигналы",
    "майнинг", "облачный майнинг",
    "airdrop", "аирдроп", "пампим", "памп",
    "p2p заработок", "арбитраж крипты",
    "пассивный заработок", "деньги на автомате",

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
    "бонус при регистрации", "фрибет",

    # 18+
    "интим", "эскорт", "массаж для мужчин",
    "знакомства 18", "девушки на час",
    "досуг", "сопровождение",

    # Общий спам
    "дам денег", "раздаю деньги",
    "халява", "бесплатно раздаю",
    "срочно!!!", "только сегодня",
    "последний шанс", "эксклюзивное предложение",
    "переходи по ссылке", "жми на ссылку",
    "подписывайся на канал",
    "ищу людей", "нужны срочно",
]

# Корни слов для частичного поиска
SPAM_ROOTS = [
    "заработ", "зарабат", "зароботок", "заробот",
    "крипт", "инвест", "трейдинг", "трейдер",
    "казин", "ставк",
    "вакансi", "вакансия", "вакансии",
    "подработ", "приработ",
]

# Подозрительные паттерны (regex)
SPAM_PATTERNS = [
    # Деньги и оплата
    r"(?:от|до)\s*\d+\s*(?:₽|руб|рублей|р|к|тыс|тысяч|\$|долл|euro|евро)",
    r"\d+\s*(?:₽|руб|рублей)\s*(?:в\s*)?(?:час|день|неделю|месяц)",
    r"(?:от|до)\s*\d{3,}\s*(?:в\s*)?(?:час|день|неделю)",
    r"\d{4,}\s*(?:₽|руб|рублей|р\.)",

    # Призывы в ЛС (ключевое для скрытого спама!)
    r"(?:пиш[иу]|напиш[иу])(?:те)?\s*(?:в\s*)?(?:лс|личк|л\.с\.|дм|dm|директ)",
    r"(?:связь|общение|детали|подробност|уточнени|информаци|условия)\s*(?:в|через)\s*(?:лс|личк|л\.с\.)",
    r"(?:звон[и|я]|позвон)[и|я]?(?:те)?",
    r"(?:звоните|пишите)\s*(?:звоните|пишите)",

    # Телефоны (российские)
    r"(?:\+7|8)[\s\-]?\(?9\d{2}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}",
    r"\+?\d{10,12}",

    # Ссылки
    r"t\.me/[a-zA-Z0-9_]+",
    r"bit\.ly/",
    r"@[a-zA-Z0-9_]{5,}",

    # Работа/услуги
    r"требу[юе]тся?\s*\d+",
    r"\d+\s*(?:человек|людей|чел)\s*(?:на|для|в)",
    r"(?:нужн[ыо]|ищем|ищу|набираем)\s*\d*\s*(?:человек|людей|чел|сотрудник|специалист|помощник)",
    r"(?:готов[ыа]?|мог[у|ем])\s+(?:выйти|выехать|приехать|помочь)",
    r"(?:любые|все|всякие)\s*(?:работы|услуги)",
    r"\d+[\-‑–]\d+\s*(?:человек|чел|людей)",

    # НОВОЕ: Скрытые паттерны работы
    r"(?:ищу|нужен|требуется)\s*(?:специалист|помощник|человек)",
    r"предлагается\s*(?:работа|подработка)",
    r"(?:лёгк|легк|несложн|прост)[ая]\s*(?:работа|подработка)",
    r"(?:небольш|мелк|прост)[ие]\s*(?:поручени|задани)",
]

# Слова-индикаторы работы (для комбинаций)
WORK_INDICATORS = [
    "работа", "работу", "подработка", "подработку",
    "поручения", "поручений", "задания", "заданий",
    "специалист", "помощник", "сотрудник",
    "опыт", "график", "расписание",
    "оплата", "зарплата", "доход",
]

# Слова-индикаторы призыва в ЛС
DM_INDICATORS = [
    "в лс", "в личку", "в л.с.", "через личку",
    "пишите", "пиши", "напишите", "напиши",
    "связь", "обращайтесь", "свяжитесь",
]

# Комбинированные паттерны (если 2+ совпадений - спам)
SPAM_COMBO_WORDS = [
    "звоните", "пишите", "звони", "пиши",
    "услуги", "работы", "помощь",
    "недорого", "дешево", "цена", "цены",
    "готов", "готовы", "могу", "можем",
    "выезд", "выезжаем", "приеду", "приедем",
]

# ============== ЛОГИРОВАНИЕ ==============
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============== СТРУКТУРЫ ДАННЫХ ==============

@dataclass
class UserProfile:
    """Профиль пользователя для анализа поведения"""
    user_id: int
    first_seen: datetime = field(default_factory=datetime.now)
    message_count: int = 0
    spam_score: float = 0.0
    warnings: int = 0
    messages_deleted: int = 0
    last_message_time: datetime = None
    message_hashes: List[str] = field(default_factory=list)


class MessageSimilarityChecker:
    """Детектор похожих/дублирующихся сообщений"""

    def __init__(self, similarity_threshold: float = 0.85, window_minutes: int = 30):
        self.threshold = similarity_threshold
        self.window = timedelta(minutes=window_minutes)
        # {chat_id: [(user_id, text_hash, normalized_text, timestamp), ...]}
        self.recent_messages: Dict[int, List[Tuple]] = defaultdict(list)

    def _get_hash(self, text: str) -> str:
        normalized = text.lower().strip()
        normalized = ' '.join(normalized.split())
        return hashlib.md5(normalized.encode()).hexdigest()[:16]

    def _simple_similarity(self, text1: str, text2: str) -> float:
        """Простое сравнение по словам"""
        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())
        if not words1 or not words2:
            return 0.0
        intersection = words1 & words2
        union = words1 | words2
        return len(intersection) / len(union)

    def check(self, text: str, user_id: int, chat_id: int) -> Tuple[bool, str]:
        """Проверить, является ли сообщение дубликатом"""
        if len(text) < 30:
            return False, ""

        now = datetime.now()
        text_hash = self._get_hash(text)
        normalized = text.lower().strip()

        # Очищаем старые записи
        cutoff = now - self.window
        self.recent_messages[chat_id] = [
            msg for msg in self.recent_messages[chat_id]
            if msg[3] > cutoff
        ]

        # Проверяем на дубликаты
        for stored_user_id, stored_hash, stored_text, _ in self.recent_messages[chat_id]:
            # Точное совпадение хеша
            if stored_hash == text_hash and stored_user_id != user_id:
                return True, "точный дубликат от другого пользователя"

            # Похожий текст от разных пользователей
            if stored_user_id != user_id:
                similarity = self._simple_similarity(normalized, stored_text)
                if similarity >= self.threshold:
                    return True, f"похожее сообщение ({similarity:.0%})"

        # Сохраняем текущее сообщение
        self.recent_messages[chat_id].append((user_id, text_hash, normalized, now))

        return False, ""


class UserBehaviorAnalyzer:
    """Анализатор поведения пользователей"""

    def __init__(self):
        self.profiles: Dict[int, UserProfile] = {}
        # Флуд-контроль: {user_id: [timestamps]}
        self.message_times: Dict[int, List[datetime]] = defaultdict(list)

    def get_profile(self, user_id: int) -> UserProfile:
        if user_id not in self.profiles:
            self.profiles[user_id] = UserProfile(user_id=user_id)
        return self.profiles[user_id]

    def record_message(self, user_id: int):
        """Записать сообщение пользователя"""
        now = datetime.now()
        profile = self.get_profile(user_id)
        profile.message_count += 1
        profile.last_message_time = now

        # Флуд-контроль
        self.message_times[user_id].append(now)
        # Оставляем только последнюю минуту
        cutoff = now - timedelta(minutes=1)
        self.message_times[user_id] = [t for t in self.message_times[user_id] if t > cutoff]

    def is_flooding(self, user_id: int) -> bool:
        """Проверить, флудит ли пользователь"""
        return len(self.message_times.get(user_id, [])) > 10  # >10 сообщений в минуту

    def record_spam(self, user_id: int):
        """Записать спам от пользователя"""
        profile = self.get_profile(user_id)
        profile.warnings += 1
        profile.messages_deleted += 1
        profile.spam_score += 0.3

    def is_suspicious(self, user_id: int) -> bool:
        """Проверить, подозрительный ли пользователь"""
        profile = self.get_profile(user_id)
        return profile.spam_score >= 0.5 or profile.warnings >= 2

    def analyze_user_profile(self, user: User) -> Tuple[bool, List[str]]:
        """Анализ профиля пользователя на подозрительность"""
        red_flags = []

        # Удалённый аккаунт (нет имени)
        if not user.first_name or user.first_name.lower() in ["deleted", "удалённый"]:
            red_flags.append("удалённый аккаунт")

        # Нет юзернейма
        if not user.username:
            red_flags.append("нет username")

        # Подозрительные имена
        suspicious_names = ["deleted", "account", "user", "test", "admin", "support"]
        full_name = (user.first_name or "").lower() + " " + (user.last_name or "").lower()
        if any(name in full_name for name in suspicious_names):
            red_flags.append("подозрительное имя")

        is_suspicious = len(red_flags) >= 2
        return is_suspicious, red_flags


# ============== ИНИЦИАЛИЗАЦИЯ ==============

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()

# Хранилища
pending_verification: Dict[int, dict] = {}
verified_users: Set[int] = set()

# Анализаторы
similarity_checker = MessageSimilarityChecker()
behavior_analyzer = UserBehaviorAnalyzer()

# Статистика
stats = {
    "spam_deleted": 0,
    "users_verified": 0,
    "users_kicked": 0,
    "duplicates_blocked": 0,
    "suspicious_users_blocked": 0,
    "start_time": datetime.now()
}


# ============== ФУНКЦИИ ПРОВЕРКИ СПАМА ==============

def normalize_text(text: str) -> str:
    """Нормализация текста для поиска спама"""
    text = text.lower()

    # Замена латинских букв на кириллицу (антиобход)
    replacements = {
        'a': 'а', 'e': 'е', 'o': 'о', 'p': 'р', 'c': 'с',
        'x': 'х', 'y': 'у', 'k': 'к', 'h': 'н', 'm': 'м',
        'b': 'в', 't': 'т', 'i': 'и', 'n': 'н',
    }
    for lat, cyr in replacements.items():
        text = text.replace(lat, cyr)

    # Удаление zero-width символов
    zero_width = '\u200b\u200c\u200d\u200e\u200f\u2060\u2061\u2062\u2063\u2064\ufeff'
    for char in zero_width:
        text = text.replace(char, '')

    # Нормализация пробелов
    text = re.sub(r'[^\w\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text)

    return text.strip()


def check_work_dm_combo(text: str) -> Tuple[bool, str]:
    """Проверка комбинации: работа + призыв в ЛС = 100% спам"""
    normalized = normalize_text(text)

    has_work = any(word in normalized for word in WORK_INDICATORS)
    has_dm = any(word in normalized for word in DM_INDICATORS)

    if has_work and has_dm:
        return True, "работа + призыв в ЛС"

    return False, ""


def is_spam(text: str) -> Tuple[bool, str]:
    """Комплексная проверка сообщения на спам"""
    if not text:
        return False, ""

    normalized = normalize_text(text)
    original_lower = text.lower()

    # 1. Проверка комбинации работа + ЛС (самый частый скрытый спам)
    is_work_dm, reason = check_work_dm_combo(text)
    if is_work_dm:
        return True, reason

    # 2. Проверка по ключевым словам
    for keyword in SPAM_KEYWORDS:
        if keyword in normalized:
            return True, f"ключевое слово: {keyword}"

    # 3. Проверка по корням слов
    for root in SPAM_ROOTS:
        if root in normalized:
            return True, f"корень слова: {root}"

    # 4. Проверка по regex паттернам
    for pattern in SPAM_PATTERNS:
        if re.search(pattern, original_lower):
            return True, f"паттерн: {pattern[:30]}..."

    # 5. Проверка комбинаций (2+ слов = спам)
    combo_count = 0
    found_combos = []
    for word in SPAM_COMBO_WORDS:
        if word in normalized:
            combo_count += 1
            found_combos.append(word)
    if combo_count >= 2:
        return True, f"комбинация: {', '.join(found_combos[:3])}"

    # 6. Номер телефона + призыв = спам
    has_phone = bool(re.search(r'(?:\+7|8)?\d{10,11}', re.sub(r'[\s\-\(\)]', '', text)))
    has_call_to_action = any(w in normalized for w in ["звоните", "пишите", "звони", "пиши", "обращайтесь"])
    if has_phone and has_call_to_action:
        return True, "телефон + призыв"

    # 7. Избыток эмодзи
    emoji_count = len(re.findall(r'[\U0001F300-\U0001F9FF]', text))
    if emoji_count > 7:
        return True, f"много эмодзи: {emoji_count}"

    return False, ""


async def advanced_spam_check(message: Message) -> Tuple[bool, str, float]:
    """
    Продвинутая проверка на спам с учётом поведения и контекста
    Возвращает: (is_spam, reason, confidence)
    """
    text = message.text or message.caption or ""
    user_id = message.from_user.id
    chat_id = message.chat.id
    user = message.from_user

    confidence = 0.0
    reasons = []

    # 1. Анализ профиля пользователя
    is_suspicious_user, red_flags = behavior_analyzer.analyze_user_profile(user)
    if is_suspicious_user:
        confidence += 0.3
        reasons.extend(red_flags)

    # 2. Проверка на флуд
    if behavior_analyzer.is_flooding(user_id):
        confidence += 0.25
        reasons.append("флуд")

    # 3. Проверка на дубликаты
    is_duplicate, dup_reason = similarity_checker.check(text, user_id, chat_id)
    if is_duplicate:
        confidence += 0.4
        reasons.append(dup_reason)
        stats["duplicates_blocked"] += 1

    # 4. Проверка истории пользователя
    if behavior_analyzer.is_suspicious(user_id):
        confidence += 0.2
        reasons.append("подозрительная история")

    # 5. Базовая проверка на спам
    is_spam_basic, spam_reason = is_spam(text)
    if is_spam_basic:
        confidence += 0.5
        reasons.append(spam_reason)

    # 6. Дополнительный анализ для "чистых" сообщений от подозрительных профилей
    if not is_spam_basic and is_suspicious_user:
        # Если профиль подозрительный и сообщение похоже на рекламу
        ad_words = ["ищу", "нужен", "требуется", "предлагаю", "предлагается", "готов", "могу"]
        if any(word in text.lower() for word in ad_words):
            confidence += 0.2
            reasons.append("реклама от подозрительного профиля")

    # Финальное решение
    is_spam_final = confidence >= 0.5

    return is_spam_final, ", ".join(reasons) if reasons else "", min(confidence, 1.0)


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
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
            await bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
            await asyncio.sleep(1)
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

    # Пропускаем ботов
    if user.is_bot:
        return

    # Пропускаем админов
    if user.id in ADMIN_IDS:
        verified_users.add(user.id)
        return

    # Если уже верифицирован
    if user.id in verified_users:
        return

    # Анализ профиля на входе
    is_suspicious, red_flags = behavior_analyzer.analyze_user_profile(user)
    if is_suspicious:
        logger.warning(f"Suspicious user joined: {user.id} - {red_flags}")
        stats["suspicious_users_blocked"] += 1

    try:
        # Ограничиваем права
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

    if callback.from_user.id != user_id:
        await callback.answer("❌ Эта кнопка не для вас!", show_alert=True)
        return

    chat_id = callback.message.chat.id

    try:
        if user_id in pending_verification:
            pending_verification[user_id]["task"].cancel()
            pending_verification.pop(user_id, None)

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

        verified_users.add(user_id)
        stats["users_verified"] += 1

        await callback.message.edit_text(
            f"✅ <b>{callback.from_user.full_name}</b> верифицирован!\n\n"
            f"Добро пожаловать в чат! 🎉",
            parse_mode="HTML"
        )

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

    # Записываем активность
    behavior_analyzer.record_message(message.from_user.id)

    # Получаем текст
    text = message.text or message.caption or ""

    # Продвинутая проверка на спам
    spam_detected, reason, confidence = await advanced_spam_check(message)

    if spam_detected:
        try:
            await message.delete()
            stats["spam_deleted"] += 1
            behavior_analyzer.record_spam(message.from_user.id)

            user_name = message.from_user.full_name or message.from_user.username
            logger.info(f"Spam deleted from {user_name} ({message.from_user.id}): {reason} [{confidence:.0%}]")

            # Уведомление
            warn_msg = await message.answer(
                f"🚫 Сообщение удалено.\n"
                f"<i>Причина: {reason}</i>",
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
    """Статистика бота"""
    if message.from_user.id not in ADMIN_IDS:
        return

    uptime = datetime.now() - stats["start_time"]
    hours = int(uptime.total_seconds() // 3600)
    minutes = int((uptime.total_seconds() % 3600) // 60)

    await message.answer(
        f"📊 <b>Статистика спам-фильтра v2.0</b>\n\n"
        f"⏱ Аптайм: {hours}ч {minutes}м\n"
        f"🗑 Удалено спама: {stats['spam_deleted']}\n"
        f"🔄 Дубликатов: {stats['duplicates_blocked']}\n"
        f"👤 Подозрительных: {stats['suspicious_users_blocked']}\n"
        f"✅ Верифицировано: {stats['users_verified']}\n"
        f"🚫 Кикнуто: {stats['users_kicked']}\n"
        f"👥 В базе: {len(verified_users)}",
        parse_mode="HTML"
    )


@router.message(Command("spam_add"))
async def cmd_add_keyword(message: Message):
    """Добавить ключевое слово"""
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
        "🤖 <b>Команды спам-фильтра v2.0</b>\n\n"
        "/spam_stats — статистика бота\n"
        "/spam_add <слово> — добавить стоп-слово\n"
        "/spam_help — эта справка\n\n"
        "<b>Возможности:</b>\n"
        "• Верификация кнопкой (60 сек)\n"
        "• 100+ ключевых слов\n"
        "• Детекция скрытого спама\n"
        "• Обнаружение дубликатов\n"
        "• Анализ профилей\n"
        "• Защита от обхода (латиница→кириллица)",
        parse_mode="HTML"
    )


@router.message(Command("start"))
async def cmd_start(message: Message):
    """Приветствие в личных сообщениях"""
    if message.chat.type != "private":
        return

    is_admin = message.from_user.id in ADMIN_IDS

    await message.answer(
        "🛡 <b>Спам-фильтр бот v2.0</b>\n\n"
        "Я защищаю чаты от спама и ботов.\n\n"
        "<b>Что я умею:</b>\n"
        "• Верификация новых участников\n"
        "• Умная фильтрация спама\n"
        "• Детекция скрытых предложений работы\n"
        "• Обнаружение дубликатов сообщений\n"
        "• Анализ подозрительных профилей\n"
        "• Защита от обхода фильтров\n\n"
        "<b>Как подключить:</b>\n"
        "1. Добавьте меня в группу\n"
        "2. Назначьте администратором\n"
        "3. Дайте права: удалять сообщения, банить\n\n"
        + ("👑 <b>Вы администратор бота</b>\n"
           "Команды: /spam_stats, /spam_add, /spam_help" if is_admin else ""),
        parse_mode="HTML"
    )


async def main():
    """Запуск бота"""
    logger.info("Starting spam filter bot v2.0...")

    dp.include_router(router)
    await bot.delete_webhook(drop_pending_updates=True)

    logger.info("Bot started successfully!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
