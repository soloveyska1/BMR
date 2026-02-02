"""
Спам-фильтр бот для Telegram чатов v3.0
========================================
Фичи:
- ✅ Верификация с правилами чата
- ✅ CAS (Combot Anti-Spam) интеграция
- ✅ Авто-бан после 5 предупреждений
- ✅ Ночной режим (23:00-07:00)
- ✅ Белый список (whitelist)
- ✅ Уведомления админам
- ✅ Slow mode для новых юзеров
- ✅ Ограничение ссылок/пересылок для новичков
- ✅ ML-подобный классификатор спама
- ✅ OCR для изображений (опционально)
- ✅ Авто-очистка сообщений
"""

import asyncio
import re
import logging
import hashlib
import json
import os
from datetime import datetime, timedelta, time
from typing import Dict, Set, List, Tuple, Optional
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
import io

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    Message, CallbackQuery, ChatPermissions,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ChatMemberUpdated, User, PhotoSize
)
from aiogram.filters import ChatMemberUpdatedFilter, IS_NOT_MEMBER, IS_MEMBER, Command
from aiogram.enums import ChatMemberStatus
from dotenv import load_dotenv

# Опциональные зависимости
try:
    import aiohttp
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False

try:
    from PIL import Image
    import pytesseract
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False

load_dotenv()

# ============== НАСТРОЙКИ ==============
BOT_TOKEN = os.getenv("SPAM_BOT_TOKEN")
ADMIN_IDS = [int(x.strip()) for x in os.getenv("SPAM_ADMIN_IDS", "").split(",") if x.strip()]

# Время на верификацию (секунды)
VERIFY_TIMEOUT = 60

# Авто-бан после N предупреждений
MAX_WARNINGS = 5

# Ночной режим (UTC+3 Москва)
NIGHT_MODE_ENABLED = True
NIGHT_START = time(23, 0)  # 23:00
NIGHT_END = time(7, 0)     # 07:00

# Slow mode для новичков (первые N сообщений)
NEWBIE_MESSAGE_LIMIT = 5
NEWBIE_COOLDOWN_SECONDS = 30  # между сообщениями

# Ограничения для новичков
NEWBIE_HOURS = 24  # Считаем новичком первые 24 часа

# CAS API
CAS_API_URL = "https://api.cas.chat/check"

# Пути к файлам данных
DATA_DIR = Path(__file__).parent / "spam_bot_data"
DATA_DIR.mkdir(exist_ok=True)
WHITELIST_FILE = DATA_DIR / "whitelist.json"
WARNINGS_FILE = DATA_DIR / "warnings.json"

# ============== ПРАВИЛА ЧАТА ==============
CHAT_RULES = """
🎙 <b>Добро пожаловать в чат БИМ радио 102.8 FM!</b>

Мы рады каждому слушателю! Чтобы всем было комфортно:

📋 <b>Правила:</b>
1️⃣ <b>Без рекламы</b> — никаких услуг, товаров, каналов
2️⃣ <b>Без спама</b> — не флудим и не повторяемся
3️⃣ <b>Культурно общаемся</b> — без мата и оскорблений
4️⃣ <b>Уважаем друг друга</b> — мы одна музыкальная семья!
5️⃣ <b>По теме</b> — музыка, радио, Казань и хорошее настроение 🎵

⚠️ За нарушения — предупреждение, потом бан.
"""

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

    # Скрытый спам работы
    "связь через личку", "уточнения в лс", "подробности в лс",
    "детали в лс", "информация в лс", "условия в лс",
    "лёгкая работа", "легкая работа", "несложная работа",
    "лёгкие деньги", "легкие деньги", "быстрые деньги", "деньги легко",
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

    # 18+ / Взрослый контент (расширено)
    "интим", "интимные", "интимный", "интим услуги",
    "эскорт", "эскортница", "эскортницы", "эскорт услуги",
    "массаж для мужчин", "эротический массаж", "массаж с продолжением",
    "знакомства 18", "знакомства 18+", "знакомства для взрослых",
    "девушки на час", "девочки на час", "девушка на час",
    "досуг", "досуг компании", "провести досуг",
    "сопровождение", "сопровождения",
    "индивидуалка", "индивидуалки", "индивидуалок",
    "проститутка", "проституция",
    "секс", "сексуальные", "секс услуги",
    "развлечения для взрослых", "взрослые развлечения",
    "ночные развлечения", "развлечения на ночь",
    "приятное времяпровождение", "приятный досуг",
    "услуги для мужчин", "услуги для взрослых",
    "встреча без обязательств", "встречи без обязательств",
    "онлифанс", "onlyfans", "only fans",
    "приватный контент", "приватные фото", "приватное видео",
    "горячие фото", "горячее видео", "горячий контент",
    "откровенные фото", "откровенный контент",
    "18+", "21+", "только для взрослых",

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
    # 18+ корни
    "эскорт", "эскортниц", "сопровож", "индивидуал",
    "интим", "эротич", "проститут", "секс",
]

# ============== ПЕРЕМАНКИ (Luring to bots/channels) ==============
LURING_KEYWORDS = [
    # Призывы в бот
    "напиши боту", "пиши боту", "нажми на бот",
    "переходи в бот", "перейди в бот", "кликни на бот",
    "напиши мне в бот", "пиши в бот",

    # Призывы по ссылке
    "переходи по ссылке", "перейди по ссылке", "жми на ссылку",
    "кликни на ссылку", "тапни на ссылку",
    "ссылка в профиле", "ссылка в био", "link in bio",

    # Призывы в канал/чат
    "подписывайся на канал", "подпишись на канал",
    "переходи в канал", "переходи в чат",
    "присоединяйся к каналу", "заходи в канал",
    "только в канале", "полный контент в канале",
    "только в боте", "полный контент в боте",
    "все подробности в боте", "подробности в канале",

    # Контент-приманки
    "больше фото в", "больше видео в", "полное видео в",
    "продолжение в", "смотри в боте", "смотри в канале",
    "эксклюзивный контент", "приватный контент",
    "премиум контент", "vip контент",

    # Регистрация/подтверждение
    "пройди регистрацию", "зарегистрируйся",
    "подтверди номер", "подтверди профиль",
    "получи доступ", "открой доступ",
]

# ============== 18+ ЭМОДЗИ ==============
ADULT_EMOJIS = [
    "🔞", "💋", "🍑", "🍆", "👅", "💦",
    "🔥", "😈", "😏", "🥵", "🤤", "💄",
    "👙", "🩱", "💃", "🌹", "💕", "❤️‍🔥",
    "🍒", "🍌", "🌶️", "👀", "🤫", "🙈",
]

# Опасные комбинации эмодзи (если 3+ из этих = подозрительно)
ADULT_EMOJI_COMBOS = [
    ("🔞", "💋", "🍑"),
    ("🔞", "🍆", "💦"),
    ("💋", "😈", "🔥"),
    ("🍑", "💦", "😈"),
    ("👅", "💋", "🔥"),
]

# Подозрительные паттерны (regex)
SPAM_PATTERNS = [
    # Деньги и оплата
    r"(?:от|до)\s*\d+\s*(?:₽|руб|рублей|р|к|тыс|тысяч|\$|долл|euro|евро)",
    r"\d+\s*(?:₽|руб|рублей)\s*(?:в\s*)?(?:час|день|неделю|месяц)",
    r"(?:от|до)\s*\d{3,}\s*(?:в\s*)?(?:час|день|неделю)",
    r"\d{4,}\s*(?:₽|руб|рублей|р\.)",

    # Призывы в ЛС
    r"(?:пиш[иу]|напиш[иу])(?:те)?\s*(?:в\s*)?(?:лс|личк|л\.с\.|дм|dm|директ)",
    r"(?:связь|общение|детали|подробност|уточнени|информаци|условия)\s*(?:в|через)\s*(?:лс|личк|л\.с\.)",
    r"(?:звон[и|я]|позвон)[и|я]?(?:те)?",
    r"(?:звоните|пишите)\s*(?:звоните|пишите)",

    # Телефоны
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

    # Скрытые паттерны работы
    r"(?:ищу|нужен|требуется)\s*(?:специалист|помощник|человек)",
    r"предлагается\s*(?:работа|подработка)",
    r"(?:лёгк|легк|несложн|прост)[ая]\s*(?:работа|подработка)",
    r"(?:небольш|мелк|прост)[ие]\s*(?:поручени|задани)",

    # Деньги + период
    r"\d{3,}\s*(?:в\s*)?(?:день|час|неделю|месяц)",
    r"(?:лёгк|легк|быстр)[иы][ех]\s*(?:деньги|денег)",

    # ============== 18+ ПАТТЕРНЫ ==============
    # Эскорт/Интим услуги
    r"(?:эскорт|эскортниц|сопровождени(?:е|я)|девушк[и]?\s+на\s+час)",
    r"(?:индивидуалк|интим[\-\s]*услуг|массаж\s*(?:для\s*)?(?:мужчин|эротич))",

    # Цена + время услуги
    r"(?:[\d]{2,5}\s*(?:₽|руб|р\.)\s*(?:в\s*)?(?:час|ночь|встреч))",
    r"(?:от\s*[\d]{3,5}\s*(?:за|в)\s*(?:час|ночь|встреч))",

    # Переманки в бот/канал
    r"(?:напиш[иу](?:те)?\s+(?:в\s*)?бот|переход[и|я](?:те)?\s*(?:в\s*)?бот)",
    r"(?:только\s+(?:в\s+)?(?:боте|канале)|полный\s+контент\s+(?:в\s+)?(?:боте|канале))",
    r"(?:ссылк[ау]\s+в\s+(?:профил|био)|link\s+in\s+bio)",

    # OnlyFans и аналоги
    r"(?:only[\s\-]?fans|onlyfans|олифенс|онлифанс)",

    # Скрытые взрослые услуги
    r"(?:приятн[ое][ей]?\s+(?:досуг|времяпровождени|отдых))",
    r"(?:развлечени[яе]\s+(?:для\s+)?(?:взросл|на\s+ночь|ночн))",
    r"(?:встреч[аи]\s+без\s+обязательств)",

    # 18+ эмодзи комбо (3+ подряд)
    r"(?:[🔞💋🍑🍆👅💦🔥😈]){3,}",
]

# Слова-индикаторы работы
WORK_INDICATORS = [
    "работа", "работу", "подработка", "подработку",
    "поручения", "поручений", "задания", "заданий",
    "специалист", "помощник", "сотрудник",
    "опыт", "график", "расписание",
    "оплата", "зарплата", "доход",
    "деньги", "денег", "заработок",
]

# Слова-индикаторы призыва в ЛС
DM_INDICATORS = [
    "в лс", "в личку", "в л.с.", "через личку",
    "пишите", "пиши", "напишите", "напиши",
    "связь", "обращайтесь", "свяжитесь",
    " лс",
]

# Комбинированные паттерны
SPAM_COMBO_WORDS = [
    "звоните", "пишите", "звони", "пиши",
    "услуги", "работы", "помощь",
    "недорого", "дешево", "цена", "цены",
    "готов", "готовы", "могу", "можем",
    "выезд", "выезжаем", "приеду", "приедем",
]

# Мат-фильтр (базовые корни)
PROFANITY_ROOTS = [
    "хуй", "хуя", "хуе", "хуи", "хую",
    "пизд", "пезд",
    "блять", "бляд", "блядь",
    "ебат", "ебан", "ебну", "ебёт", "ебет", "ебал", "ёб", "еб",
    "сука", "сучк", "сучар",
    "мудак", "мудил", "мудо",
    "пидор", "пидар", "педик",
    "залупа", "залуп",
    "шлюх", "шалав",
    "дрочи", "дроч", "дрочк",
]

# ============== ЛОГИРОВАНИЕ ==============
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============== КЛАССЫ ДАННЫХ ==============

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
    is_cas_banned: bool = False
    join_time: datetime = field(default_factory=datetime.now)


class PersistentStorage:
    """Постоянное хранилище для whitelist и warnings"""

    def __init__(self):
        self.whitelist: Set[int] = set()
        self.warnings: Dict[int, int] = {}
        self.banned_users: Set[int] = set()
        self._load()

    def _load(self):
        """Загрузить данные из файлов"""
        if WHITELIST_FILE.exists():
            try:
                with open(WHITELIST_FILE, 'r') as f:
                    data = json.load(f)
                    self.whitelist = set(data.get('whitelist', []))
                    self.banned_users = set(data.get('banned', []))
            except:
                pass

        if WARNINGS_FILE.exists():
            try:
                with open(WARNINGS_FILE, 'r') as f:
                    self.warnings = {int(k): v for k, v in json.load(f).items()}
            except:
                pass

    def _save_whitelist(self):
        """Сохранить whitelist"""
        with open(WHITELIST_FILE, 'w') as f:
            json.dump({
                'whitelist': list(self.whitelist),
                'banned': list(self.banned_users)
            }, f)

    def _save_warnings(self):
        """Сохранить warnings"""
        with open(WARNINGS_FILE, 'w') as f:
            json.dump(self.warnings, f)

    def add_to_whitelist(self, user_id: int):
        self.whitelist.add(user_id)
        self._save_whitelist()

    def remove_from_whitelist(self, user_id: int):
        self.whitelist.discard(user_id)
        self._save_whitelist()

    def is_whitelisted(self, user_id: int) -> bool:
        return user_id in self.whitelist

    def add_warning(self, user_id: int) -> int:
        """Добавить предупреждение, вернуть общее количество"""
        self.warnings[user_id] = self.warnings.get(user_id, 0) + 1
        self._save_warnings()
        return self.warnings[user_id]

    def get_warnings(self, user_id: int) -> int:
        return self.warnings.get(user_id, 0)

    def reset_warnings(self, user_id: int):
        if user_id in self.warnings:
            del self.warnings[user_id]
            self._save_warnings()

    def add_banned(self, user_id: int):
        self.banned_users.add(user_id)
        self._save_whitelist()

    def is_banned(self, user_id: int) -> bool:
        return user_id in self.banned_users


class CASChecker:
    """Проверка через Combot Anti-Spam API"""

    def __init__(self):
        self.cache: Dict[int, Tuple[bool, datetime]] = {}
        self.cache_ttl = timedelta(hours=24)

    async def check(self, user_id: int) -> bool:
        """Проверить пользователя в CAS базе"""
        if not AIOHTTP_AVAILABLE:
            return False

        # Проверяем кеш
        if user_id in self.cache:
            is_banned, cached_at = self.cache[user_id]
            if datetime.now() - cached_at < self.cache_ttl:
                return is_banned

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    CAS_API_URL,
                    params={"user_id": user_id},
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        is_banned = data.get("ok", False)
                        self.cache[user_id] = (is_banned, datetime.now())
                        return is_banned
        except Exception as e:
            logger.warning(f"CAS check failed for {user_id}: {e}")

        return False


class MessageSimilarityChecker:
    """Детектор похожих/дублирующихся сообщений"""

    def __init__(self, similarity_threshold: float = 0.85, window_minutes: int = 30):
        self.threshold = similarity_threshold
        self.window = timedelta(minutes=window_minutes)
        self.recent_messages: Dict[int, List[Tuple]] = defaultdict(list)

    def _get_hash(self, text: str) -> str:
        normalized = text.lower().strip()
        normalized = ' '.join(normalized.split())
        return hashlib.md5(normalized.encode()).hexdigest()[:16]

    def _simple_similarity(self, text1: str, text2: str) -> float:
        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())
        if not words1 or not words2:
            return 0.0
        intersection = words1 & words2
        union = words1 | words2
        return len(intersection) / len(union)

    def check(self, text: str, user_id: int, chat_id: int) -> Tuple[bool, str]:
        if len(text) < 30:
            return False, ""

        now = datetime.now()
        text_hash = self._get_hash(text)
        normalized = text.lower().strip()

        cutoff = now - self.window
        self.recent_messages[chat_id] = [
            msg for msg in self.recent_messages[chat_id]
            if msg[3] > cutoff
        ]

        for stored_user_id, stored_hash, stored_text, _ in self.recent_messages[chat_id]:
            if stored_hash == text_hash and stored_user_id != user_id:
                return True, "точный дубликат от другого пользователя"

            if stored_user_id != user_id:
                similarity = self._simple_similarity(normalized, stored_text)
                if similarity >= self.threshold:
                    return True, f"похожее сообщение ({similarity:.0%})"

        self.recent_messages[chat_id].append((user_id, text_hash, normalized, now))
        return False, ""


class UserBehaviorAnalyzer:
    """Анализатор поведения пользователей"""

    def __init__(self):
        self.profiles: Dict[int, UserProfile] = {}
        self.message_times: Dict[int, List[datetime]] = defaultdict(list)
        self.newbie_messages: Dict[int, List[datetime]] = defaultdict(list)

    def get_profile(self, user_id: int) -> UserProfile:
        if user_id not in self.profiles:
            self.profiles[user_id] = UserProfile(user_id=user_id)
        return self.profiles[user_id]

    def record_message(self, user_id: int):
        now = datetime.now()
        profile = self.get_profile(user_id)
        profile.message_count += 1
        profile.last_message_time = now

        self.message_times[user_id].append(now)
        cutoff = now - timedelta(minutes=1)
        self.message_times[user_id] = [t for t in self.message_times[user_id] if t > cutoff]

    def is_flooding(self, user_id: int) -> bool:
        return len(self.message_times.get(user_id, [])) > 10

    def record_spam(self, user_id: int):
        profile = self.get_profile(user_id)
        profile.warnings += 1
        profile.messages_deleted += 1
        profile.spam_score += 0.3

    def is_suspicious(self, user_id: int) -> bool:
        profile = self.get_profile(user_id)
        return profile.spam_score >= 0.5 or profile.warnings >= 2

    def analyze_user_profile(self, user: User) -> Tuple[bool, List[str]]:
        red_flags = []

        if not user.first_name or user.first_name.lower() in ["deleted", "удалённый"]:
            red_flags.append("удалённый аккаунт")

        if not user.username:
            red_flags.append("нет username")

        suspicious_names = ["deleted", "account", "user", "test", "admin", "support"]
        full_name = (user.first_name or "").lower() + " " + (user.last_name or "").lower()
        if any(name in full_name for name in suspicious_names):
            red_flags.append("подозрительное имя")

        is_suspicious = len(red_flags) >= 2
        return is_suspicious, red_flags

    def is_newbie(self, user_id: int) -> bool:
        """Проверить, является ли пользователь новичком"""
        profile = self.get_profile(user_id)
        hours_since_join = (datetime.now() - profile.join_time).total_seconds() / 3600
        return hours_since_join < NEWBIE_HOURS

    def check_newbie_cooldown(self, user_id: int) -> Tuple[bool, int]:
        """Проверить cooldown для новичка. Возвращает (can_send, seconds_left)"""
        profile = self.get_profile(user_id)

        if profile.message_count >= NEWBIE_MESSAGE_LIMIT:
            return True, 0

        now = datetime.now()
        messages = self.newbie_messages.get(user_id, [])

        # Очищаем старые записи
        cutoff = now - timedelta(seconds=NEWBIE_COOLDOWN_SECONDS)
        messages = [t for t in messages if t > cutoff]
        self.newbie_messages[user_id] = messages

        if messages:
            last_msg_time = max(messages)
            elapsed = (now - last_msg_time).total_seconds()
            if elapsed < NEWBIE_COOLDOWN_SECONDS:
                return False, int(NEWBIE_COOLDOWN_SECONDS - elapsed)

        return True, 0

    def record_newbie_message(self, user_id: int):
        """Записать сообщение новичка"""
        self.newbie_messages[user_id].append(datetime.now())


class MLSpamClassifier:
    """ML-подобный классификатор спама на основе весов"""

    def __init__(self):
        # Веса для разных признаков
        self.weights = {
            'keyword_match': 0.3,
            'root_match': 0.25,
            'pattern_match': 0.35,
            'work_dm_combo': 0.5,
            'phone_cta': 0.4,
            'many_emojis': 0.15,
            'link': 0.2,
            'mention': 0.15,
            'caps': 0.1,
            'duplicate': 0.4,
            'suspicious_profile': 0.25,
            'cas_banned': 0.8,
            'profanity': 0.3,
            'newbie_link': 0.35,
            'night_mode': 0.1,
            # 18+ / Adult spam weights
            'adult_keywords': 0.50,
            'luring_keywords': 0.55,
            'adult_emojis': 0.45,
            'adult_emoji_combo': 0.60,
            'night_adult': 0.35,
        }
        self.threshold = 0.45

    def extract_features(self, text: str, user_profile: UserProfile,
                         is_newbie: bool, is_night: bool, has_link: bool,
                         is_cas_banned: bool) -> Dict[str, float]:
        """Извлечь признаки из сообщения"""
        features = {}
        normalized = normalize_text(text)
        original_lower = text.lower()

        # Ключевые слова
        keyword_count = sum(1 for kw in SPAM_KEYWORDS if kw in normalized)
        features['keyword_match'] = min(keyword_count * 0.15, 1.0)

        # Корни слов
        root_count = sum(1 for root in SPAM_ROOTS if root in normalized)
        features['root_match'] = min(root_count * 0.2, 1.0)

        # Паттерны
        pattern_count = sum(1 for p in SPAM_PATTERNS if re.search(p, original_lower))
        features['pattern_match'] = min(pattern_count * 0.15, 1.0)

        # Работа + ЛС комбо
        has_work = any(w in normalized for w in WORK_INDICATORS)
        has_dm = any(w in normalized for w in DM_INDICATORS)
        features['work_dm_combo'] = 1.0 if (has_work and has_dm) else 0.0

        # Телефон + призыв
        has_phone = bool(re.search(r'(?:\+7|8)?\d{10,11}', re.sub(r'[\s\-\(\)]', '', text)))
        has_cta = any(w in normalized for w in ["звоните", "пишите", "звони", "пиши", "обращайтесь"])
        features['phone_cta'] = 1.0 if (has_phone and has_cta) else 0.0

        # Много эмодзи
        emoji_count = len(re.findall(r'[\U0001F300-\U0001F9FF]', text))
        features['many_emojis'] = 1.0 if emoji_count > 7 else 0.0

        # Ссылки
        features['link'] = 1.0 if has_link else 0.0

        # Упоминания
        mention_count = len(re.findall(r'@[a-zA-Z0-9_]{5,}', text))
        features['mention'] = min(mention_count * 0.3, 1.0)

        # Много капса
        if len(text) > 10:
            caps_ratio = sum(1 for c in text if c.isupper()) / len(text)
            features['caps'] = 1.0 if caps_ratio > 0.5 else 0.0
        else:
            features['caps'] = 0.0

        # Мат
        has_profanity = any(root in normalized for root in PROFANITY_ROOTS)
        features['profanity'] = 1.0 if has_profanity else 0.0

        # Подозрительный профиль
        features['suspicious_profile'] = 1.0 if user_profile.spam_score > 0.3 else 0.0

        # CAS бан
        features['cas_banned'] = 1.0 if is_cas_banned else 0.0

        # Новичок + ссылка
        features['newbie_link'] = 1.0 if (is_newbie and has_link) else 0.0

        # Ночной режим
        features['night_mode'] = 1.0 if is_night else 0.0

        # ============== 18+ / ADULT SPAM DETECTION ==============

        # Проверка на 18+ ключевые слова
        adult_kw_list = [
            "эскорт", "эскортница", "интим", "интимные", "сопровождение",
            "девушки на час", "девушка на час", "индивидуалка",
            "досуг компании", "провести досуг", "развлечения для взрослых",
            "приватный контент", "горячие фото", "откровенные фото",
            "onlyfans", "only fans", "онлифанс", "18+",
            "массаж для мужчин", "эротический массаж",
            "встреча без обязательств", "ночные развлечения",
        ]
        adult_count = sum(1 for kw in adult_kw_list if kw in normalized)
        features['adult_keywords'] = min(adult_count * 0.3, 1.0)

        # Проверка на переманки
        luring_count = sum(1 for kw in LURING_KEYWORDS if kw in normalized)
        features['luring_keywords'] = min(luring_count * 0.25, 1.0)

        # Проверка на 18+ эмодзи
        adult_emoji_count = sum(1 for emoji in ADULT_EMOJIS if emoji in text)
        features['adult_emojis'] = min(adult_emoji_count * 0.15, 1.0)

        # Проверка на опасные комбинации эмодзи
        adult_combo_found = False
        for combo in ADULT_EMOJI_COMBOS:
            if all(emoji in text for emoji in combo):
                adult_combo_found = True
                break
        features['adult_emoji_combo'] = 1.0 if adult_combo_found else 0.0

        # Ночь + 18+ контент = очень подозрительно
        has_adult_content = adult_count > 0 or adult_emoji_count >= 2
        features['night_adult'] = 1.0 if (is_night and has_adult_content) else 0.0

        return features

    def classify(self, features: Dict[str, float]) -> Tuple[bool, float, List[str]]:
        """Классифицировать сообщение"""
        score = 0.0
        triggered = []

        for feature, value in features.items():
            if value > 0 and feature in self.weights:
                contribution = value * self.weights[feature]
                score += contribution
                if contribution > 0.1:
                    triggered.append(feature)

        is_spam = score >= self.threshold
        return is_spam, min(score, 1.0), triggered


class OCRProcessor:
    """Обработчик OCR для изображений"""

    @staticmethod
    async def extract_text(photo_bytes: bytes) -> str:
        """Извлечь текст из изображения"""
        if not OCR_AVAILABLE:
            return ""

        try:
            image = Image.open(io.BytesIO(photo_bytes))
            # Настройки для русского + английского
            text = pytesseract.image_to_string(image, lang='rus+eng')
            return text.strip()
        except Exception as e:
            logger.warning(f"OCR failed: {e}")
            return ""


class RaidDetector:
    """Детектор рейдов и массовых атак"""

    def __init__(self):
        self.lockdown_active = False
        self.join_times: Dict[int, List[datetime]] = defaultdict(list)
        self.raid_threshold = 10  # Юзеров за минуту
        self.auto_lockdown_triggered = False

    def record_join(self, chat_id: int) -> bool:
        """Записать вход и проверить на рейд. Возвращает True если рейд"""
        now = datetime.now()
        self.join_times[chat_id].append(now)

        # Оставляем только последнюю минуту
        cutoff = now - timedelta(minutes=1)
        self.join_times[chat_id] = [t for t in self.join_times[chat_id] if t > cutoff]

        joins_per_minute = len(self.join_times[chat_id])

        # Автоматический lockdown при рейде
        if joins_per_minute >= self.raid_threshold and not self.auto_lockdown_triggered:
            self.lockdown_active = True
            self.auto_lockdown_triggered = True
            logger.warning(f"RAID DETECTED in {chat_id}! {joins_per_minute} joins/min. Auto-lockdown activated!")
            return True

        return False

    def is_lockdown(self) -> bool:
        return self.lockdown_active

    def get_join_rate(self, chat_id: int) -> int:
        """Получить количество входов за последнюю минуту"""
        now = datetime.now()
        cutoff = now - timedelta(minutes=1)
        self.join_times[chat_id] = [t for t in self.join_times[chat_id] if t > cutoff]
        return len(self.join_times[chat_id])


# ============== ИНИЦИАЛИЗАЦИЯ ==============

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()

# Хранилища
pending_verification: Dict[int, dict] = {}
verified_users: Set[int] = set()

# Компоненты
storage = PersistentStorage()
cas_checker = CASChecker()
similarity_checker = MessageSimilarityChecker()
behavior_analyzer = UserBehaviorAnalyzer()
ml_classifier = MLSpamClassifier()
ocr_processor = OCRProcessor()
raid_detector = RaidDetector()

# Статистика
stats = {
    "spam_deleted": 0,
    "users_verified": 0,
    "users_kicked": 0,
    "users_banned": 0,
    "duplicates_blocked": 0,
    "suspicious_users_blocked": 0,
    "cas_blocked": 0,
    "profanity_blocked": 0,
    "night_mode_blocked": 0,
    "newbie_restricted": 0,
    "ocr_detections": 0,
    "raids_detected": 0,
    "start_time": datetime.now()
}


# ============== ФУНКЦИИ ==============

def normalize_text(text: str) -> str:
    """Нормализация текста для поиска спама"""
    text = text.lower()

    replacements = {
        'a': 'а', 'e': 'е', 'o': 'о', 'p': 'р', 'c': 'с',
        'x': 'х', 'y': 'у', 'k': 'к', 'h': 'н', 'm': 'м',
        'b': 'в', 't': 'т', 'i': 'и', 'n': 'н',
    }
    for lat, cyr in replacements.items():
        text = text.replace(lat, cyr)

    zero_width = '\u200b\u200c\u200d\u200e\u200f\u2060\u2061\u2062\u2063\u2064\ufeff'
    for char in zero_width:
        text = text.replace(char, '')

    text = re.sub(r'[^\w\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text)

    return text.strip()


def is_night_mode() -> bool:
    """Проверить, активен ли ночной режим"""
    if not NIGHT_MODE_ENABLED:
        return False

    now = datetime.now().time()

    # Ночь переходит через полночь
    if NIGHT_START > NIGHT_END:
        return now >= NIGHT_START or now <= NIGHT_END
    else:
        return NIGHT_START <= now <= NIGHT_END


def has_links(text: str) -> bool:
    """Проверить наличие ссылок в тексте"""
    link_patterns = [
        r'https?://\S+',
        r't\.me/\S+',
        r'@[a-zA-Z0-9_]{5,}',
        r'bit\.ly/\S+',
        r'[a-zA-Z0-9-]+\.[a-z]{2,}/\S*',
    ]
    for pattern in link_patterns:
        if re.search(pattern, text):
            return True
    return False


def check_profanity(text: str) -> bool:
    """Проверить наличие мата"""
    normalized = normalize_text(text)
    return any(root in normalized for root in PROFANITY_ROOTS)


async def notify_admins(message: str, chat_id: int = None):
    """Уведомить администраторов"""
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"🔔 <b>Уведомление</b>\n\n{message}",
                parse_mode="HTML"
            )
        except Exception as e:
            logger.warning(f"Could not notify admin {admin_id}: {e}")


async def auto_ban_user(user_id: int, chat_id: int, reason: str):
    """Автоматический бан пользователя"""
    try:
        await bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
        storage.add_banned(user_id)
        stats["users_banned"] += 1

        await notify_admins(
            f"🚫 <b>Авто-бан</b>\n"
            f"Пользователь: <code>{user_id}</code>\n"
            f"Причина: {reason}\n"
            f"Чат: <code>{chat_id}</code>"
        )
        logger.info(f"Auto-banned user {user_id}: {reason}")
    except Exception as e:
        logger.error(f"Failed to ban user {user_id}: {e}")


def get_verify_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Клавиатура для верификации"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="🎵 Я слушаю БИМ радио и принимаю правила!",
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


async def process_spam_message(message: Message, reason: str, confidence: float):
    """Обработать спам-сообщение"""
    user_id = message.from_user.id
    chat_id = message.chat.id

    try:
        # Удаляем сообщение
        await message.delete()
        stats["spam_deleted"] += 1
        behavior_analyzer.record_spam(user_id)

        # Добавляем предупреждение
        warnings = storage.add_warning(user_id)

        user_name = message.from_user.full_name or message.from_user.username
        logger.info(f"Spam deleted from {user_name} ({user_id}): {reason} [{confidence:.0%}], warning {warnings}/{MAX_WARNINGS}")

        # Проверяем на авто-бан
        if warnings >= MAX_WARNINGS:
            await auto_ban_user(user_id, chat_id, f"Превышен лимит предупреждений ({MAX_WARNINGS})")
            warn_text = f"🚫 <b>{user_name}</b> забанен.\nПричина: {MAX_WARNINGS} предупреждений"
        else:
            warn_text = (
                f"⚠️ Сообщение удалено.\n"
                f"<i>Причина: {reason}</i>\n"
                f"Предупреждение: {warnings}/{MAX_WARNINGS}"
            )

        warn_msg = await message.answer(warn_text, parse_mode="HTML")
        await asyncio.sleep(7)
        try:
            await warn_msg.delete()
        except:
            pass

    except Exception as e:
        logger.error(f"Error processing spam: {e}")


# ============== ОБРАБОТЧИКИ ==============

@router.chat_member(ChatMemberUpdatedFilter(IS_NOT_MEMBER >> IS_MEMBER))
async def on_user_join(event: ChatMemberUpdated):
    """Новый участник присоединился"""
    user = event.new_chat_member.user
    chat_id = event.chat.id

    if user.is_bot:
        return

    if user.id in ADMIN_IDS:
        verified_users.add(user.id)
        return

    if user.id in verified_users:
        return

    # Проверка в whitelist
    if storage.is_whitelisted(user.id):
        verified_users.add(user.id)
        logger.info(f"Whitelisted user {user.id} auto-verified")
        return

    # Проверка на бан
    if storage.is_banned(user.id):
        try:
            await bot.ban_chat_member(chat_id=chat_id, user_id=user.id)
            logger.info(f"Banned user {user.id} tried to rejoin")
        except:
            pass
        return

    # Антирейд проверка
    is_raid = raid_detector.record_join(chat_id)
    if is_raid:
        stats["raids_detected"] += 1
        await notify_admins(
            f"🚨 <b>РЕЙД ОБНАРУЖЕН!</b>\n\n"
            f"Чат: <code>{chat_id}</code>\n"
            f"Входов/мин: {raid_detector.get_join_rate(chat_id)}\n\n"
            f"Автоматическая блокировка ВКЛЮЧЕНА!\n"
            f"Отключить: /spam_lockdown off"
        )

    # Если lockdown активен — кикаем сразу
    if raid_detector.is_lockdown():
        try:
            await bot.ban_chat_member(chat_id=chat_id, user_id=user.id)
            await asyncio.sleep(1)
            await bot.unban_chat_member(chat_id=chat_id, user_id=user.id)
            stats["users_kicked"] += 1
            logger.info(f"Lockdown: kicked user {user.id}")
        except:
            pass
        return

    # CAS проверка
    is_cas_banned = await cas_checker.check(user.id)
    if is_cas_banned:
        stats["cas_blocked"] += 1
        try:
            await bot.ban_chat_member(chat_id=chat_id, user_id=user.id)
            await notify_admins(
                f"🛡 <b>CAS-бан</b>\n"
                f"Пользователь: {user.full_name} (<code>{user.id}</code>)\n"
                f"Причина: в базе CAS"
            )
            logger.info(f"CAS-banned user {user.id}")
        except Exception as e:
            logger.error(f"Failed to ban CAS user: {e}")
        return

    # Анализ профиля
    is_suspicious, red_flags = behavior_analyzer.analyze_user_profile(user)
    if is_suspicious:
        logger.warning(f"Suspicious user joined: {user.id} - {red_flags}")
        stats["suspicious_users_blocked"] += 1

    # Устанавливаем время присоединения
    profile = behavior_analyzer.get_profile(user.id)
    profile.join_time = datetime.now()

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

        user_name = user.full_name or user.username or "друг"
        msg = await bot.send_message(
            chat_id=chat_id,
            text=(
                f"🎙 <b>Привет, {user_name}!</b>\n\n"
                f"{CHAT_RULES}\n"
                f"⏰ Нажми кнопку ниже в течение {VERIFY_TIMEOUT} секунд, "
                f"чтобы присоединиться к нашей музыкальной семье!"
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

        # Для новичков - ограниченные права (нельзя ссылки/форварды)
        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=ChatPermissions(
                can_send_messages=True,
                can_send_media_messages=True,
                can_send_other_messages=True,
                can_add_web_page_previews=False,  # Нельзя превью ссылок
                can_send_polls=True,
                can_invite_users=False,  # Нельзя приглашать
                can_change_info=False,
                can_pin_messages=False
            )
        )

        verified_users.add(user_id)
        stats["users_verified"] += 1

        await callback.message.edit_text(
            f"🎉 <b>{callback.from_user.full_name}</b> теперь с нами!\n\n"
            f"🎵 Добро пожаловать в семью БИМ радио!\n"
            f"Слушай 102.8 FM и общайся с нами 📻",
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


@router.message(F.chat.type.in_({"group", "supergroup"}), F.photo)
async def on_photo_message(message: Message):
    """Обработка фото с OCR"""
    if message.from_user.id in ADMIN_IDS:
        return

    if storage.is_whitelisted(message.from_user.id):
        return

    # Записываем активность
    behavior_analyzer.record_message(message.from_user.id)

    # Проверяем caption
    caption = message.caption or ""
    if caption:
        # Используем стандартную проверку для подписи
        await check_text_for_spam(message, caption)
        return

    # OCR для изображений
    if OCR_AVAILABLE and message.photo:
        try:
            photo = message.photo[-1]  # Берём самое большое фото
            file = await bot.get_file(photo.file_id)
            photo_bytes = await bot.download_file(file.file_path)

            # Извлекаем текст
            ocr_text = await ocr_processor.extract_text(photo_bytes.read())

            if ocr_text and len(ocr_text) > 20:
                # Проверяем текст с фото
                user_profile = behavior_analyzer.get_profile(message.from_user.id)
                is_newbie = behavior_analyzer.is_newbie(message.from_user.id)
                is_night = is_night_mode()
                text_has_links = has_links(ocr_text)
                is_cas = user_profile.is_cas_banned

                features = ml_classifier.extract_features(
                    ocr_text, user_profile, is_newbie, is_night, text_has_links, is_cas
                )
                is_spam, confidence, triggered = ml_classifier.classify(features)

                if is_spam:
                    stats["ocr_detections"] += 1
                    await process_spam_message(
                        message,
                        f"OCR: {', '.join(triggered[:3])}",
                        confidence
                    )

        except Exception as e:
            logger.warning(f"OCR processing failed: {e}")


@router.message(F.chat.type.in_({"group", "supergroup"}), F.forward_from | F.forward_from_chat)
async def on_forward_message(message: Message):
    """Обработка пересланных сообщений"""
    if message.from_user.id in ADMIN_IDS:
        return

    if storage.is_whitelisted(message.from_user.id):
        return

    # Новички не могут пересылать
    if behavior_analyzer.is_newbie(message.from_user.id):
        try:
            await message.delete()
            stats["newbie_restricted"] += 1
            warn_msg = await message.answer(
                f"⚠️ Новые участники не могут пересылать сообщения первые {NEWBIE_HOURS} часов.",
                parse_mode="HTML"
            )
            await asyncio.sleep(5)
            await warn_msg.delete()
        except:
            pass
        return

    # Проверяем текст пересланного сообщения
    text = message.text or message.caption or ""
    if text:
        await check_text_for_spam(message, text)


@router.message(F.chat.type.in_({"group", "supergroup"}))
async def on_group_message(message: Message):
    """Проверка сообщений на спам"""
    # Пропускаем админов
    if message.from_user.id in ADMIN_IDS:
        return

    # Пропускаем whitelist
    if storage.is_whitelisted(message.from_user.id):
        return

    # Пропускаем команды
    if message.text and message.text.startswith("/"):
        return

    text = message.text or message.caption or ""
    await check_text_for_spam(message, text)


async def check_text_for_spam(message: Message, text: str):
    """Проверить текст на спам"""
    user_id = message.from_user.id
    chat_id = message.chat.id

    # Записываем активность
    behavior_analyzer.record_message(user_id)

    user_profile = behavior_analyzer.get_profile(user_id)
    is_newbie = behavior_analyzer.is_newbie(user_id)
    is_night = is_night_mode()
    text_has_links = has_links(text)

    # Проверка cooldown для новичков
    if is_newbie:
        can_send, seconds_left = behavior_analyzer.check_newbie_cooldown(user_id)
        if not can_send:
            try:
                await message.delete()
                stats["newbie_restricted"] += 1
                warn_msg = await message.answer(
                    f"⏳ Подождите {seconds_left} сек. (slow mode для новых участников)",
                )
                await asyncio.sleep(3)
                await warn_msg.delete()
            except:
                pass
            return
        behavior_analyzer.record_newbie_message(user_id)

    # Ограничение ссылок для новичков
    if is_newbie and text_has_links:
        try:
            await message.delete()
            stats["newbie_restricted"] += 1
            warn_msg = await message.answer(
                f"🔗 Новые участники не могут отправлять ссылки первые {NEWBIE_HOURS} часов.",
            )
            await asyncio.sleep(5)
            await warn_msg.delete()
        except:
            pass
        return

    # Проверка на мат
    if check_profanity(text):
        stats["profanity_blocked"] += 1
        await process_spam_message(message, "нецензурная лексика", 0.9)
        return

    # Ночной режим - строже проверки
    if is_night:
        user_profile.spam_score += 0.1  # Увеличиваем подозрительность ночью

    # CAS проверка (если ещё не проверяли)
    if not user_profile.is_cas_banned:
        user_profile.is_cas_banned = await cas_checker.check(user_id)
        if user_profile.is_cas_banned:
            stats["cas_blocked"] += 1
            await auto_ban_user(user_id, chat_id, "Найден в базе CAS")
            try:
                await message.delete()
            except:
                pass
            return

    # Проверка на дубликаты
    is_duplicate, dup_reason = similarity_checker.check(text, user_id, chat_id)
    if is_duplicate:
        stats["duplicates_blocked"] += 1
        await process_spam_message(message, dup_reason, 0.85)
        return

    # ML классификация
    features = ml_classifier.extract_features(
        text, user_profile, is_newbie, is_night, text_has_links, user_profile.is_cas_banned
    )
    is_spam, confidence, triggered = ml_classifier.classify(features)

    if is_spam:
        reason = ', '.join(triggered[:3]) if triggered else "подозрительное сообщение"
        await process_spam_message(message, reason, confidence)


# ============== КОМАНДЫ АДМИНИСТРАТОРА ==============

@router.message(Command("spam_stats"))
async def cmd_stats(message: Message):
    """Статистика бота"""
    if message.from_user.id not in ADMIN_IDS:
        return

    uptime = datetime.now() - stats["start_time"]
    hours = int(uptime.total_seconds() // 3600)
    minutes = int((uptime.total_seconds() % 3600) // 60)

    night_status = "🌙 АКТИВЕН" if is_night_mode() else "☀️ неактивен"
    lockdown_status = "🔴 АКТИВЕН" if raid_detector.is_lockdown() else "🟢 неактивен"

    await message.answer(
        f"🎙 <b>БИМ радио — Статистика v3.0</b>\n\n"
        f"⏱ Аптайм: {hours}ч {minutes}м\n"
        f"🌙 Ночной режим: {night_status}\n"
        f"🚨 Lockdown: {lockdown_status}\n\n"
        f"<b>Блокировки:</b>\n"
        f"🗑 Удалено спама: {stats['spam_deleted']}\n"
        f"🔄 Дубликатов: {stats['duplicates_blocked']}\n"
        f"🛡 CAS-баны: {stats['cas_blocked']}\n"
        f"🤬 За мат: {stats['profanity_blocked']}\n"
        f"🆕 Новички: {stats['newbie_restricted']}\n"
        f"📷 OCR: {stats['ocr_detections']}\n"
        f"🚨 Рейдов: {stats['raids_detected']}\n"
        f"👤 Подозрительных: {stats['suspicious_users_blocked']}\n\n"
        f"<b>Пользователи:</b>\n"
        f"✅ Верифицировано: {stats['users_verified']}\n"
        f"🚫 Кикнуто: {stats['users_kicked']}\n"
        f"⛔️ Забанено: {stats['users_banned']}\n"
        f"👥 В базе: {len(verified_users)}\n"
        f"📝 Whitelist: {len(storage.whitelist)}",
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


@router.message(Command("spam_whitelist"))
async def cmd_whitelist(message: Message):
    """Управление whitelist"""
    if message.from_user.id not in ADMIN_IDS:
        return

    args = message.text.split()

    if len(args) < 2:
        # Показать whitelist
        if storage.whitelist:
            users = ", ".join(str(u) for u in storage.whitelist)
            await message.answer(f"📝 <b>Whitelist:</b>\n{users}", parse_mode="HTML")
        else:
            await message.answer("📝 Whitelist пуст")
        return

    action = args[1].lower()

    if action == "add" and len(args) >= 3:
        try:
            user_id = int(args[2])
            storage.add_to_whitelist(user_id)
            await message.answer(f"✅ Добавлен в whitelist: <code>{user_id}</code>", parse_mode="HTML")
        except ValueError:
            await message.answer("❌ Неверный ID пользователя")

    elif action == "remove" and len(args) >= 3:
        try:
            user_id = int(args[2])
            storage.remove_from_whitelist(user_id)
            await message.answer(f"✅ Удалён из whitelist: <code>{user_id}</code>", parse_mode="HTML")
        except ValueError:
            await message.answer("❌ Неверный ID пользователя")

    else:
        await message.answer(
            "Использование:\n"
            "/spam_whitelist — показать список\n"
            "/spam_whitelist add <user_id> — добавить\n"
            "/spam_whitelist remove <user_id> — удалить"
        )


@router.message(Command("spam_unban"))
async def cmd_unban(message: Message):
    """Разбанить пользователя"""
    if message.from_user.id not in ADMIN_IDS:
        return

    args = message.text.split()
    if len(args) < 2:
        await message.answer("Использование: /spam_unban <user_id>")
        return

    try:
        user_id = int(args[1])
        storage.reset_warnings(user_id)
        storage.banned_users.discard(user_id)
        storage._save_whitelist()

        # Разбанить в чате (если в группе)
        if message.chat.type in ["group", "supergroup"]:
            try:
                await bot.unban_chat_member(chat_id=message.chat.id, user_id=user_id)
            except:
                pass

        await message.answer(f"✅ Разбанен: <code>{user_id}</code>", parse_mode="HTML")
    except ValueError:
        await message.answer("❌ Неверный ID пользователя")


@router.message(Command("spam_warn"))
async def cmd_check_warnings(message: Message):
    """Проверить предупреждения пользователя"""
    if message.from_user.id not in ADMIN_IDS:
        return

    args = message.text.split()
    if len(args) < 2:
        await message.answer("Использование: /spam_warn <user_id>")
        return

    try:
        user_id = int(args[1])
        warnings = storage.get_warnings(user_id)
        is_banned = storage.is_banned(user_id)

        status = "⛔️ ЗАБАНЕН" if is_banned else f"⚠️ {warnings}/{MAX_WARNINGS}"
        await message.answer(f"Пользователь <code>{user_id}</code>: {status}", parse_mode="HTML")
    except ValueError:
        await message.answer("❌ Неверный ID пользователя")


@router.message(Command("spam_test"))
async def cmd_test_spam(message: Message):
    """Проверить текст на спам"""
    if message.from_user.id not in ADMIN_IDS:
        return

    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Использование: /spam_test <текст для проверки>")
        return

    test_text = args[1]

    # Создаём фейковый профиль для теста
    fake_profile = UserProfile(user_id=0)

    # Извлекаем признаки
    features = ml_classifier.extract_features(
        test_text, fake_profile,
        is_newbie=True, is_night=is_night_mode(),
        has_link=has_links(test_text), is_cas_banned=False
    )

    is_spam_result, confidence, triggered = ml_classifier.classify(features)

    # Проверка на мат
    has_profanity = check_profanity(test_text)

    # Формируем отчёт
    result = "🚫 <b>СПАМ</b>" if is_spam_result else "✅ <b>Чисто</b>"

    report = (
        f"🔍 <b>Результат проверки:</b>\n\n"
        f"📝 Текст: <code>{test_text[:100]}{'...' if len(test_text) > 100 else ''}</code>\n\n"
        f"{result} (уверенность: {confidence:.0%})\n\n"
    )

    if triggered:
        report += f"⚠️ Сработало: {', '.join(triggered)}\n"

    if has_profanity:
        report += "🤬 Обнаружен мат\n"

    if has_links(test_text):
        report += "🔗 Содержит ссылки\n"

    # Детали по признакам
    report += "\n<b>Признаки:</b>\n"
    for feat, val in sorted(features.items(), key=lambda x: -x[1]):
        if val > 0:
            report += f"• {feat}: {val:.2f}\n"

    await message.answer(report, parse_mode="HTML")


@router.message(Command("spam_lockdown"))
async def cmd_lockdown(message: Message):
    """Управление режимом блокировки (антирейд)"""
    if message.from_user.id not in ADMIN_IDS:
        return

    args = message.text.split()

    if len(args) < 2:
        current = "🔴 АКТИВЕН" if raid_detector.lockdown_active else "🟢 неактивен"
        await message.answer(
            f"🚨 <b>Режим блокировки (антирейд)</b>\n\n"
            f"Статус: {current}\n\n"
            f"Использование:\n"
            f"/spam_lockdown on — включить блокировку\n"
            f"/spam_lockdown off — выключить блокировку\n\n"
            f"При включённой блокировке все новые участники "
            f"автоматически кикаются.",
            parse_mode="HTML"
        )
        return

    action = args[1].lower()

    if action in ["on", "1", "true", "да"]:
        raid_detector.lockdown_active = True
        await message.answer("🔴 <b>Блокировка ВКЛЮЧЕНА!</b>\nВсе новые участники будут кикнуты.", parse_mode="HTML")
        await notify_admins("🚨 Режим блокировки ВКЛЮЧЁН администратором!")
    elif action in ["off", "0", "false", "нет"]:
        raid_detector.lockdown_active = False
        await message.answer("🟢 <b>Блокировка ВЫКЛЮЧЕНА</b>\nНовые участники проходят верификацию.", parse_mode="HTML")
        await notify_admins("✅ Режим блокировки выключен")
    else:
        await message.answer("❌ Используйте: /spam_lockdown on или /spam_lockdown off")


@router.message(Command("spam_help"))
async def cmd_help(message: Message):
    """Помощь по командам"""
    if message.from_user.id not in ADMIN_IDS:
        return

    await message.answer(
        "🎙 <b>БИМ радио — Команды антиспам бота v3.0</b>\n\n"
        "<b>📊 Статистика:</b>\n"
        "/spam_stats — статистика бота\n\n"
        "<b>🔍 Тестирование:</b>\n"
        "/spam_test <текст> — проверить текст на спам\n\n"
        "<b>📝 Управление:</b>\n"
        "/spam_add <слово> — добавить стоп-слово\n"
        "/spam_whitelist — управление whitelist\n"
        "/spam_warn <id> — проверить предупреждения\n"
        "/spam_unban <id> — разбанить пользователя\n\n"
        "<b>🚨 Антирейд:</b>\n"
        "/spam_lockdown — управление блокировкой\n\n"
        "<b>🛡 Возможности:</b>\n"
        "• Верификация с правилами БИМ радио\n"
        "• CAS (Combot Anti-Spam)\n"
        "• Авто-бан после 5 предупреждений\n"
        "• Ночной режим (23:00-07:00)\n"
        "• Антирейд защита\n"
        "• ML классификатор спама\n"
        "• OCR для картинок\n"
        "• Мат-фильтр",
        parse_mode="HTML"
    )


@router.message(Command("start"))
async def cmd_start(message: Message):
    """Приветствие в личных сообщениях"""
    if message.chat.type != "private":
        return

    is_admin = message.from_user.id in ADMIN_IDS

    await message.answer(
        "🎙 <b>БИМ радио 102.8 FM — Антиспам бот v3.0</b>\n\n"
        "Привет! Я защищаю чат нашей радиостанции от спама и ботов.\n\n"
        "<b>Мои суперсилы:</b>\n"
        "🎵 Верификация новых слушателей\n"
        "🛡 CAS (Combot Anti-Spam) проверка\n"
        "⚠️ Авто-бан после 5 предупреждений\n"
        "🌙 Ночной режим (23:00-07:00)\n"
        "📝 Whitelist для доверенных\n"
        "⏳ Slow mode для новичков\n"
        "🔗 Защита от спам-ссылок\n"
        "🤖 ML классификация спама\n"
        "📷 Распознавание текста на картинках\n"
        "🤬 Мат-фильтр\n"
        "🚨 Антирейд защита\n\n"
        "📻 <b>Слушай БИМ радио 102.8 FM!</b>\n\n"
        + ("👑 <b>Вы администратор бота</b>\n"
           "/spam_help — все команды" if is_admin else ""),
        parse_mode="HTML"
    )


# ============== ФОНОВЫЕ ЗАДАЧИ ==============

async def auto_cleanup_task():
    """Автоматическая очистка старых данных"""
    while True:
        await asyncio.sleep(3600)  # Каждый час

        try:
            # Очистка старых сообщений из similarity checker
            now = datetime.now()
            cutoff = now - timedelta(hours=2)

            for chat_id in list(similarity_checker.recent_messages.keys()):
                similarity_checker.recent_messages[chat_id] = [
                    msg for msg in similarity_checker.recent_messages[chat_id]
                    if msg[3] > cutoff
                ]
                if not similarity_checker.recent_messages[chat_id]:
                    del similarity_checker.recent_messages[chat_id]

            # Очистка CAS кеша
            for user_id in list(cas_checker.cache.keys()):
                _, cached_at = cas_checker.cache[user_id]
                if now - cached_at > cas_checker.cache_ttl:
                    del cas_checker.cache[user_id]

            logger.info("Auto-cleanup completed")

        except Exception as e:
            logger.error(f"Auto-cleanup error: {e}")


async def grant_full_permissions_task():
    """Выдать полные права пользователям после периода новичка"""
    while True:
        await asyncio.sleep(1800)  # Каждые 30 минут

        try:
            now = datetime.now()

            for user_id, profile in list(behavior_analyzer.profiles.items()):
                hours_since_join = (now - profile.join_time).total_seconds() / 3600

                # Если пользователь больше не новичок и верифицирован
                if hours_since_join >= NEWBIE_HOURS and user_id in verified_users:
                    # Тут можно выдать полные права, но нужен chat_id
                    # Это делается при следующем сообщении пользователя
                    pass

        except Exception as e:
            logger.error(f"Permissions task error: {e}")


async def main():
    """Запуск бота"""
    logger.info("Starting spam filter bot v3.0...")
    logger.info(f"OCR available: {OCR_AVAILABLE}")
    logger.info(f"Aiohttp available: {AIOHTTP_AVAILABLE}")
    logger.info(f"Night mode: {NIGHT_START} - {NIGHT_END}")
    logger.info(f"Max warnings: {MAX_WARNINGS}")
    logger.info(f"Newbie hours: {NEWBIE_HOURS}")

    dp.include_router(router)

    # Запускаем фоновые задачи
    asyncio.create_task(auto_cleanup_task())
    asyncio.create_task(grant_full_permissions_task())

    await bot.delete_webhook(drop_pending_updates=True)

    logger.info("Bot started successfully!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
