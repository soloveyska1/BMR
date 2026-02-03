"""
Спам-фильтр бот для Telegram чатов v4.4
========================================
Фичи:
- ✅ Верификация с правилами чата
- ✅ CAS (Combot Anti-Spam) интеграция + Rate Limiting
- ✅ Авто-бан после 5 предупреждений
- ✅ Ночной режим (23:00-07:00)
- ✅ Белый список (whitelist)
- ✅ Уведомления админам
- ✅ Slow mode для новых юзеров
- ✅ Ограничение ссылок/пересылок для новичков
- ✅ ML-подобный классификатор спама с динамическим порогом
- ✅ OCR для изображений (опционально)
- ✅ Авто-очистка сообщений
- ✅ RLO/Bidirectional атака детекция
- ✅ Периодическая очистка памяти
- ✅ Аудит логирование
- ✅ Улучшенная детекция script mixing
"""

import asyncio
import re
import logging
import hashlib
import json
import os
import unicodedata
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

# Тестеры - видят всё как обычные пользователи, но никогда не блокируются
TESTER_IDS = [8420766371]

# Версия и время деплоя (обновляется автоматически)
BOT_VERSION = "4.4"
DEPLOY_TIME = "2026-02-03 20:00 MSK"

# Лимиты памяти (для защиты от утечек)
MAX_VERIFIED_USERS = 50000  # Максимум verified_users в памяти
MAX_USER_PROFILES = 10000   # Максимум профилей в памяти
PROFILE_EXPIRE_DAYS = 30    # Удалять профили старше N дней

# Rate limiting для CAS API
CAS_RATE_LIMIT = 30         # Максимум запросов в минуту
CAS_RATE_WINDOW = 60        # Окно в секундах

# Аудит логирование (AUDIT_LOG_FILE определяется после DATA_DIR)
AUDIT_LOG_ENABLED = True
MAX_AUDIT_SIZE_MB = 50      # Максимальный размер лог файла

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
AUDIT_LOG_FILE = DATA_DIR / "audit.log"

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
    # Работа/Заработок (расширенный + разбитые варианты)
    "заработок", "заработай", "заработать", "зарабатывай", "зарабатывать",
    "работок", "за работок", "за работай", "за работать",  # Разбитые пробелом
    "зароботок", "зароботай", "заробот",  # Опечатки
    "пассивный доход", "легкий заработок", "быстрый заработок",
    "удаленная работа", "работа на дому",
    "без опыта", "без вложений", "гарантированный доход",
    "доход от", "зарплата от", "от 100к", "от 90000", "от 50000",
    "лайки за деньги", "клики за деньги", "просмотры за деньги",
    "обучение платное", "вводный курс",
    "требуются сотрудники", "набираем людей", "ищем сотрудников",
    "требуются на завтра", "требуются на сегодня", "нужны люди",
    # Вакансии (водители, курьеры и т.п.)
    "нужны водител", "нужен водитель", "требуются водител",
    "нужны курьер", "нужен курьер", "требуются курьер",
    "нужны грузчик", "нужен грузчик", "требуются грузчик",
    "нужны разнорабоч", "требуются разнорабоч",
    "нужны продавц", "требуются продавц",
    "оплата от", "оплата в день", "ежедневная оплата",
    "в день", "р день", "р/день", "руб/день", "рублей день",
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
    # Объявления о работе / услугах
    "откликнитесь", "откликнись", "отклик", "откликайтесь",
    "на руки", "на карту сразу", "оплата наличными",
    "помощь по дому", "помощь по хозяйству", "уборка квартир",
    "мыть подъезды", "уборка подъездов", "клининг",
    "нужна помощь", "нужнa помощь", "нужна пȯмȯщь",
    "работа на сегодня", "работа на завтра", "работы на",
    "рублей в час", "рублей за час", "руб в час", "руб за час",
    "часов работы", "часа работы", "час работы",

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

    # ============== КОРОТКИЕ ОБЪЯВЛЕНИЯ О РАБОТЕ ==============
    # Паттерн: сумма + часы + призыв (типа "4800\n5 часов\nОткликнитесь")
    r"\d{3,5}\s*[\n\r]+\s*\d+\s*(?:час|ч\.)",
    r"(?:откликн|отклик)[а-яё]*",
    # Помощь по дому + оплата
    r"(?:помощь|помочь)\s+(?:по\s+)?(?:дому|хозяйству|квартире).*?\d{3,}",
    r"(?:уборк|мыть|мойка|клининг).*?\d{3,}",
    # Оплата на руки
    r"\d{3,}\s*(?:₽|руб|р\.?)?\s*(?:на\s+руки|наличными|на\s+карту)",
    r"(?:оплата|платим|заплатим)\s*\d{3,}\s*(?:₽|руб|р\.?)?",
    # Работа на X часов (1-2 часа, 3-4 часа)
    r"(?:работ[аы]|рабȯт[аы])\s*(?:на|нɑ)\s*\d[\-–]\d\s*(?:час|ч\.)",
    r"\d[\-–]\d\s*(?:час|ч\.?).*?(?:оплата|\d{3,})",
    # Сумма денег как отдельная строка (4800, 5000, etc)
    r"^\d{4,5}$",
]

# Слова-индикаторы работы
WORK_INDICATORS = [
    "работа", "работу", "подработка", "подработку",
    "поручения", "поручений", "задания", "заданий",
    "специалист", "помощник", "сотрудник",
    "опыт", "график", "расписание",
    "оплата", "зарплата", "доход",
    "деньги", "денег", "заработок",
    # Объявления об услугах
    "откликнитесь", "откликнись", "откликайтесь",
    "на руки", "наличными", "на карту",
    "помощь по дому", "помощь по хозяйству",
    "уборка", "мыть", "клининг", "подъезд",
    "часов", "часа", "час",
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


# ============== АУДИТ ЛОГИРОВАНИЕ ==============

class AuditLogger:
    """Система аудит-логирования действий бота"""

    def __init__(self, log_file: Path = None, max_size_mb: int = 50):
        self.log_file = log_file or AUDIT_LOG_FILE
        self.max_size_bytes = max_size_mb * 1024 * 1024
        self.enabled = AUDIT_LOG_ENABLED

    def _rotate_if_needed(self):
        """Ротация лог-файла при превышении размера"""
        if not self.log_file.exists():
            return
        if self.log_file.stat().st_size > self.max_size_bytes:
            # Переименовываем старый файл
            backup = self.log_file.with_suffix('.log.old')
            if backup.exists():
                backup.unlink()
            self.log_file.rename(backup)

    def log(self, action: str, user_id: int = None, chat_id: int = None,
            details: str = None, severity: str = "INFO"):
        """Записать действие в аудит лог"""
        if not self.enabled:
            return

        try:
            self._rotate_if_needed()

            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            entry = {
                "ts": timestamp,
                "action": action,
                "severity": severity
            }
            if user_id:
                entry["user_id"] = user_id
            if chat_id:
                entry["chat_id"] = chat_id
            if details:
                entry["details"] = details[:500]  # Ограничиваем длину

            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        except Exception as e:
            logger.warning(f"Audit log error: {e}")

    def log_spam_detected(self, user_id: int, chat_id: int, text: str,
                          score: float, triggered: List[str]):
        """Логировать обнаружение спама"""
        self.log(
            action="SPAM_DETECTED",
            user_id=user_id,
            chat_id=chat_id,
            details=f"score={score:.2f} triggers={triggered} text={text[:100]}",
            severity="WARN"
        )

    def log_user_banned(self, user_id: int, chat_id: int, reason: str):
        """Логировать бан пользователя"""
        self.log(
            action="USER_BANNED",
            user_id=user_id,
            chat_id=chat_id,
            details=reason,
            severity="WARN"
        )

    def log_user_verified(self, user_id: int, chat_id: int):
        """Логировать верификацию пользователя"""
        self.log(
            action="USER_VERIFIED",
            user_id=user_id,
            chat_id=chat_id,
            severity="INFO"
        )

    def log_security_event(self, event_type: str, user_id: int = None,
                           chat_id: int = None, details: str = None):
        """Логировать событие безопасности"""
        self.log(
            action=f"SECURITY_{event_type}",
            user_id=user_id,
            chat_id=chat_id,
            details=details,
            severity="ALERT"
        )


# Глобальный экземпляр аудит логгера
audit_logger = AuditLogger()


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
    """Проверка через Combot Anti-Spam API с rate limiting"""

    def __init__(self):
        self.cache: Dict[int, Tuple[bool, datetime]] = {}
        self.cache_ttl = timedelta(hours=24)
        # Rate limiting
        self.request_times: List[datetime] = []
        self.rate_limit = CAS_RATE_LIMIT
        self.rate_window = CAS_RATE_WINDOW

    def _check_rate_limit(self) -> bool:
        """Проверить, не превышен ли лимит запросов"""
        now = datetime.now()
        cutoff = now - timedelta(seconds=self.rate_window)
        # Очищаем старые записи
        self.request_times = [t for t in self.request_times if t > cutoff]
        return len(self.request_times) < self.rate_limit

    def _record_request(self):
        """Записать время запроса"""
        self.request_times.append(datetime.now())

    async def check(self, user_id: int) -> bool:
        """Проверить пользователя в CAS базе"""
        if not AIOHTTP_AVAILABLE:
            return False

        # Проверяем кеш
        if user_id in self.cache:
            is_banned, cached_at = self.cache[user_id]
            if datetime.now() - cached_at < self.cache_ttl:
                return is_banned

        # Проверяем rate limit
        if not self._check_rate_limit():
            logger.warning(f"CAS rate limit exceeded, skipping check for {user_id}")
            return False

        try:
            self._record_request()
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
                    elif response.status == 429:  # Too Many Requests
                        logger.warning("CAS API rate limited us!")
                        return False
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

    def cleanup_old_profiles(self, max_profiles: int = None, expire_days: int = None):
        """Очистка старых профилей для предотвращения утечки памяти"""
        if max_profiles is None:
            max_profiles = MAX_USER_PROFILES
        if expire_days is None:
            expire_days = PROFILE_EXPIRE_DAYS

        now = datetime.now()
        cutoff = now - timedelta(days=expire_days)

        # Удаляем профили старше expire_days без активности
        old_profiles = [
            uid for uid, profile in self.profiles.items()
            if profile.last_message_time and profile.last_message_time < cutoff
        ]
        for uid in old_profiles:
            del self.profiles[uid]

        # Если всё ещё слишком много - удаляем самые старые
        if len(self.profiles) > max_profiles:
            # Сортируем по последней активности
            sorted_profiles = sorted(
                self.profiles.items(),
                key=lambda x: x[1].last_message_time or datetime.min
            )
            # Удаляем самые старые, чтобы остались max_profiles
            to_remove = len(self.profiles) - max_profiles
            for uid, _ in sorted_profiles[:to_remove]:
                del self.profiles[uid]

        # Очищаем устаревшие записи в других словарях
        for uid in list(self.message_times.keys()):
            if uid not in self.profiles:
                del self.message_times[uid]

        for uid in list(self.newbie_messages.keys()):
            if uid not in self.profiles:
                del self.newbie_messages[uid]

        return len(old_profiles)


class MLSpamClassifier:
    """ML-подобный классификатор спама на основе весов с динамическим порогом"""

    def __init__(self):
        # === ВЕСА ПО КАТЕГОРИЯМ ===
        # КРИТИЧЕСКИЕ (0.50+) - одного достаточно для спама
        # ВЫСОКИЕ (0.30-0.49) - сильный сигнал
        # СРЕДНИЕ (0.15-0.29) - умеренный сигнал
        # НИЗКИЕ (0.05-0.14) - слабый сигнал, нужна комбинация

        self.weights = {
            # === КРИТИЧЕСКИЕ (instant spam) ===
            'rlo_attack': 0.55,           # RLO/Bidirectional атака
            'cas_banned': 0.55,           # CAS бан
            'critical_keyword': 0.50,     # Слова-маркеры (заработок, эскорт)

            # === ВЫСОКИЕ ===
            'adult_emoji_combo': 0.45,    # Комбо 18+ эмодзи
            'work_dm_combo': 0.40,        # Работа + ЛС
            'luring_keywords': 0.40,      # Переманивающие слова
            'adult_keywords': 0.38,       # 18+ ключевые слова
            'duplicate': 0.35,            # Дубликат сообщения
            'short_work_ad': 0.35,        # Короткое объявление о работе
            'phone_cta': 0.32,            # Телефон + призыв
            'obfuscation_score': 0.32,    # Обфускация текста

            # === СРЕДНИЕ ===
            'pattern_match': 0.28,        # Совпадение паттернов
            'money_hours_combo': 0.28,    # Деньги + часы
            'newbie_link': 0.26,          # Новичок + ссылка
            'adult_emojis': 0.25,         # 18+ эмодзи
            'service_offer': 0.25,        # Предложение услуг
            'night_adult': 0.24,          # Ночь + 18+
            'suspicious_structure': 0.24, # Подозрительная структура
            'keyword_match': 0.22,        # Ключевые слова
            'code_mixing': 0.22,          # Смешивание языков
            'root_match': 0.20,           # Корни слов
            'profanity': 0.20,            # Мат
            'repeated_near_spam': 0.20,   # Повторный near-spam
            'fuzzy_keyword': 0.18,        # Нечёткое совпадение
            'link': 0.16,                 # Ссылка
            'suspicious_profile': 0.16,   # Подозрительный профиль

            # === НИЗКИЕ (модификаторы) ===
            'mention': 0.10,              # Упоминание
            'many_emojis': 0.08,          # Много эмодзи
            'caps': 0.06,                 # Капс
            'night_mode': 0.05,           # Ночной режим (модификатор)
        }

        # Базовые пороги
        self.base_threshold = 0.45
        self.newbie_threshold = 0.35      # Строже для новичков
        self.night_threshold = 0.40       # Строже ночью
        self.verified_threshold = 0.50    # Мягче для проверенных

    def extract_features(self, text: str, user_profile: UserProfile,
                         is_newbie: bool, is_night: bool, has_link: bool,
                         is_cas_banned: bool) -> Dict[str, float]:
        """Извлечь признаки из сообщения"""
        features = {}
        normalized = normalize_text(text)
        original_lower = text.lower()

        # === КРИТИЧЕСКИЕ СЛОВА (сами по себе = спам) ===
        critical_keywords = [
            # Заработок/работа спам
            'заработок', 'заработай', 'заработать', 'зарабатывай',
            'пассивный доход', 'легкий заработок', 'быстрый заработок',
            'доход от', 'зарплата от', 'оплата от',
            # Вакансии-спам
            'требуются сотрудники', 'набираем людей', 'нужны люди',
            'нужны водител', 'требуются водител', 'нужны курьер',
            # Крипта/инвестиции
            'криптовалют', 'биткоин', 'инвестиц', 'трейдинг',
            'пассивный заработок', 'деньги на автомате',
            # 18+ / Эскорт
            'эскорт', 'интим услуг', 'индивидуалк', 'массаж для мужчин',
            'девушки на час', 'досуг',
            # Казино
            'казино', 'ставки на спорт', '1xbet', '1win',
            # Лохотрон
            'без вложений', 'гарантированный доход',
        ]
        has_critical = any(kw in normalized for kw in critical_keywords)
        features['critical_keyword'] = 1.0 if has_critical else 0.0

        # === RLO/BIDIRECTIONAL АТАКА ===
        # Проверяем оригинальный текст на опасные символы
        features['rlo_attack'] = 1.0 if has_rlo_attack(text) else 0.0

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

        # ============== КОРОТКИЕ ОБЪЯВЛЕНИЯ О РАБОТЕ/УСЛУГАХ ==============

        # Проверка на сумму денег (3-6 цифр, возможно с пробелами: 5 000, 4800)
        money_pattern = r'\d[\d\s]{2,5}\d?\s*(?:₽|руб|р\.?|тыс|т\.р\.)?|\d{3,6}'
        has_money = bool(re.search(money_pattern, text))

        # Проверка на время/часы
        hours_pattern = r'\d+\s*(?:час|ч\.|ч\b|часов|часа)|на\s*\d[\-–]\d\s*(?:час|ч)'
        has_hours = bool(re.search(hours_pattern, original_lower))

        # Призывы к действию
        cta_words = [
            "откликнитесь", "откликнись", "откликайтесь", "отклик",
            "пишите", "пиши", "напишите", "напиши",
            "звоните", "звони", "позвоните",
            "обращайтесь", "свяжитесь",
            "в лс", "в личку", "в личные",
        ]
        has_cta = any(w in normalized for w in cta_words)

        # Слова услуг/работы
        service_words = [
            "уборка", "мыть", "мойка", "клининг", "подъезд",
            "помощь", "помочь", "нужна помощь", "требуется",
            "работа", "подработка", "оплата", "заплатим",
            "нужен", "нужна", "нужны", "ищу", "ищем",
            "услуги", "сделаю", "выполню", "готов",
        ]
        has_service = any(w in normalized for w in service_words)

        # Короткое сообщение (типичное для спам-объявлений)
        is_short = len(text) < 200

        # Многострочное короткое сообщение (типа "4800\n5 часов\nОткликнитесь")
        lines = [l.strip() for l in text.split('\n') if l.strip()]
        is_multiline_short = len(lines) >= 2 and all(len(l) < 50 for l in lines)

        # === КОМБИНИРОВАННЫЕ ПРИЗНАКИ ===

        # short_work_ad: короткое + деньги + часы + призыв
        short_work_score = 0.0
        if is_short and has_money:
            short_work_score += 0.3
        if has_hours:
            short_work_score += 0.25
        if has_cta:
            short_work_score += 0.25
        if is_multiline_short and has_money:
            short_work_score += 0.2
        features['short_work_ad'] = min(short_work_score, 1.0)

        # money_hours_combo: деньги + часы (очень типично для спама)
        features['money_hours_combo'] = 1.0 if (has_money and has_hours) else 0.0

        # service_offer: услуга + деньги/призыв
        service_score = 0.0
        if has_service and has_money:
            service_score += 0.5
        if has_service and has_cta:
            service_score += 0.3
        if has_service and has_hours:
            service_score += 0.2
        features['service_offer'] = min(service_score, 1.0)

        # ============== НОВЫЕ УМНЫЕ ФИЧИ ==============

        # 1. OBFUSCATION SCORE: Обнаружение обфускации текста
        # Проверяем оригинальный текст до нормализации
        obfuscation_score = 0.0

        # Цифры среди букв (з0р0б0т0к)
        digit_in_word = len(re.findall(r'[а-яёa-z][0-9][а-яёa-z]', original_lower))
        if digit_in_word > 0:
            obfuscation_score += min(digit_in_word * 0.3, 0.5)

        # Символы @ $ ! среди букв
        symbol_in_word = len(re.findall(r'[а-яёa-z][@$!#€][а-яёa-z]', original_lower))
        if symbol_in_word > 0:
            obfuscation_score += min(symbol_in_word * 0.3, 0.5)

        # Смешивание скриптов в одном слове (кириллица + латиница)
        words = text.split()
        mixed_script_words = 0
        suspicious_mixed_words = []
        for word in words:
            # Убираем пунктуацию для анализа
            clean_word = re.sub(r'[^\w]', '', word)
            if len(clean_word) < 3:
                continue

            cyrillic_chars = re.findall(r'[а-яёА-ЯЁ]', clean_word)
            latin_chars = re.findall(r'[a-zA-Z]', clean_word)

            if cyrillic_chars and latin_chars:
                mixed_script_words += 1
                suspicious_mixed_words.append(clean_word)

                # Особо подозрительно: латиница в середине кириллического слова
                # Например: "рaбота" (латинская 'a' среди кириллицы)
                if len(cyrillic_chars) > len(latin_chars):
                    obfuscation_score += 0.3  # Явная попытка обфускации

        if mixed_script_words > 0:
            obfuscation_score += min(mixed_script_words * 0.25, 0.5)

        # Пробелы между буквами (з а р а б о т о к)
        spaced_letters = len(re.findall(r'(?<!\S)[а-яёa-z]\s+[а-яёa-z]\s+[а-яёa-z](?!\S)', original_lower))
        if spaced_letters > 0:
            obfuscation_score += 0.4

        # Подозрительные Unicode категории (гомоглифы)
        suspicious_unicode = 0
        for char in text:
            cat = unicodedata.category(char)
            # Буквы из необычных скриптов (Greek, Coptic, etc.)
            if cat == 'Lo' or (cat == 'Ll' and ord(char) > 0x024F):
                suspicious_unicode += 1
        if suspicious_unicode > 2:
            obfuscation_score += min(suspicious_unicode * 0.15, 0.4)

        features['obfuscation_score'] = min(obfuscation_score, 1.0)

        # 2. CODE MIXING: Смешивание русского и английского
        code_mix_score = 0.0

        # Английские слова в русском контексте (спам-маркеры)
        english_spam_words = [
            'work', 'money', 'job', 'earn', 'income', 'cash', 'pay', 'salary',
            'worker', 'driver', 'manager', 'crypto', 'bitcoin', 'invest',
            'easy', 'fast', 'quick', 'free', 'bonus', 'profit', 'trading',
            'passive', 'remote', 'online', 'telegram', 'whatsapp', 'viber',
            'casino', 'bet', 'win', 'prize', 'lucky', 'vip', 'premium',
        ]
        for eng_word in english_spam_words:
            if re.search(rf'\b{eng_word}\b', original_lower):
                code_mix_score += 0.25

        # Проверяем соотношение кириллицы и латиницы в тексте
        total_cyrillic = len(re.findall(r'[а-яёА-ЯЁ]', text))
        total_latin = len(re.findall(r'[a-zA-Z]', text))

        # Если есть оба алфавита и латиницы много (>20% от кириллицы)
        if total_cyrillic > 10 and total_latin > 0:
            latin_ratio = total_latin / total_cyrillic
            if 0.1 < latin_ratio < 0.5:  # Подозрительное смешивание
                code_mix_score += 0.2
            elif latin_ratio >= 0.5:  # Сильное смешивание
                code_mix_score += 0.35

        # Латинские буквы, визуально похожие на кириллицу (a, e, o, p, c, x, y)
        # в окружении кириллицы - явная попытка обхода
        lookalike_pattern = r'[а-яёА-ЯЁ][aeopcxyAEOPCXY][а-яёА-ЯЁ]'
        lookalikes = len(re.findall(lookalike_pattern, text))
        if lookalikes > 0:
            code_mix_score += min(lookalikes * 0.3, 0.5)

        features['code_mixing'] = min(code_mix_score, 1.0)

        # 3. FUZZY KEYWORD: Нечёткое совпадение с ключевыми словами
        # Используем простое сравнение подстрок для поиска опечаток
        fuzzy_score = 0.0
        critical_keywords = [
            'заработок', 'заработай', 'работа', 'подработка', 'доход',
            'оплата', 'деньги', 'рублей', 'тысяч', 'водитель', 'курьер'
        ]
        for word in normalized.split():
            if len(word) >= 5:  # Проверяем только достаточно длинные слова
                for kw in critical_keywords:
                    # Проверяем совпадение 70%+ символов
                    if len(word) >= len(kw) - 2 and len(word) <= len(kw) + 2:
                        matches = sum(1 for a, b in zip(word, kw) if a == b)
                        similarity = matches / max(len(word), len(kw))
                        if similarity >= 0.7 and similarity < 1.0:  # Похоже, но не точно
                            fuzzy_score += 0.3
                            break
        features['fuzzy_keyword'] = min(fuzzy_score, 1.0)

        # 4. SUSPICIOUS STRUCTURE: Подозрительная структура
        structure_score = 0.0

        # Очень короткое сообщение с числами
        if len(text) < 100 and has_money:
            structure_score += 0.3

        # Много строк, каждая короткая (типичный спам-формат)
        if is_multiline_short:
            structure_score += 0.2

        # Заканчивается призывом к действию
        last_words = normalized.split()[-3:] if normalized else []
        cta_endings = ['пишите', 'звоните', 'откликнитесь', 'пиши', 'звони']
        if any(w in last_words for w in cta_endings):
            structure_score += 0.3

        features['suspicious_structure'] = min(structure_score, 1.0)

        # 5. REPEATED NEAR SPAM: Проверяем историю пользователя
        # (будет использоваться вместе с behavior_analyzer)
        features['repeated_near_spam'] = min(user_profile.spam_score * 1.5, 1.0)

        return features

    def get_dynamic_threshold(self, is_newbie: bool, is_night: bool,
                               is_verified: bool) -> float:
        """Получить динамический порог на основе контекста"""
        if is_verified and not is_newbie:
            threshold = self.verified_threshold
        elif is_newbie:
            threshold = self.newbie_threshold
        elif is_night:
            threshold = self.night_threshold
        else:
            threshold = self.base_threshold

        return threshold

    def classify(self, features: Dict[str, float],
                 is_newbie: bool = False, is_night: bool = False,
                 is_verified: bool = False) -> Tuple[bool, float, List[str]]:
        """Классифицировать сообщение с динамическим порогом"""
        score = 0.0
        triggered = []

        for feature, value in features.items():
            if value > 0 and feature in self.weights:
                contribution = value * self.weights[feature]
                score += contribution
                if contribution > 0.08:  # Снижен порог для triggered
                    triggered.append(feature)

        # Динамический порог
        threshold = self.get_dynamic_threshold(is_newbie, is_night, is_verified)
        is_spam = score >= threshold

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

def has_rlo_attack(text: str) -> bool:
    """Проверить наличие RLO/Bidirectional атаки в тексте"""
    # Опасные bidirectional символы, которые могут скрывать текст
    dangerous_bidi = {
        '\u202a',  # Left-to-Right Embedding (LRE)
        '\u202b',  # Right-to-Left Embedding (RLE)
        '\u202c',  # Pop Directional Formatting (PDF)
        '\u202d',  # Left-to-Right Override (LRO)
        '\u202e',  # Right-to-Left Override (RLO) - самый опасный!
        '\u2066',  # Left-to-Right Isolate (LRI)
        '\u2067',  # Right-to-Left Isolate (RLI)
        '\u2068',  # First Strong Isolate (FSI)
        '\u2069',  # Pop Directional Isolate (PDI)
    }
    return any(char in text for char in dangerous_bidi)


def normalize_text(text: str) -> str:
    """Нормализация текста для поиска спама"""
    text = text.lower()

    # === ЭТАП 0: Удаление RLO/Bidirectional символов ===
    # Эти символы могут скрывать/переворачивать текст
    bidi_chars = '\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069'
    for char in bidi_chars:
        text = text.replace(char, '')

    # === ЭТАП 1: Цифры и символы → буквы (спамеры используют для обхода) ===
    digit_symbol_subs = {
        '0': 'о',  # 0 → о
        '1': 'и',  # 1 → и (или l)
        '3': 'з',  # 3 → з
        '4': 'а',  # 4 → а
        '5': 'с',  # 5 → с (или s)
        '7': 'т',  # 7 → т
        '8': 'в',  # 8 → в
        '9': 'д',  # 9 → д (похоже)
        '@': 'а',  # @ → а
        '$': 'с',  # $ → с
        '!': 'и',  # ! → и (в словах типа пиш!те)
        '#': 'н',  # # → н
        '€': 'е',  # € → е
        '₽': 'р',  # ₽ → р (но это валюта, оставим в паттернах)
    }
    for sym, cyr in digit_symbol_subs.items():
        text = text.replace(sym, cyr)

    # === ЭТАП 2: Базовые латинские → кириллица ===
    replacements = {
        # Визуально похожие
        'a': 'а', 'e': 'е', 'o': 'о', 'p': 'р', 'c': 'с',
        'x': 'х', 'y': 'у', 'k': 'к', 'h': 'н', 'm': 'м',
        'b': 'в', 't': 'т', 'i': 'и',
        # Фонетически похожие (спамеры используют)
        'n': 'п',  # nишите → пишите
        'd': 'д',  # dень → день
        'u': 'у',  # дополнительно для y/u
        'r': 'р',  # rубль → рубль (фонетически)
        's': 'с',  # sрочно → срочно
        'g': 'г',  # gород → город
        'l': 'л',  # lюди → люди
        'v': 'в',  # vодитель → водитель
        'z': 'з',  # zвоните → звоните
        'w': 'ш',  # wкола → школа (редко, но бывает)
        'f': 'ф',  # fото → фото
        'j': 'й',  # jога → йога
        'q': 'к',  # редко
    }
    for lat, cyr in replacements.items():
        text = text.replace(lat, cyr)

    # Гомоглифы (Unicode-символы, похожие на кириллицу/латиницу)
    # Спамеры используют их для обхода фильтров
    homoglyphs = {
        # А/а варианты
        'ɑ': 'а', 'α': 'а', 'а': 'а', 'ạ': 'а', 'ả': 'а', 'ã': 'а',
        'ā': 'а', 'ă': 'а', 'ặ': 'а', 'ầ': 'а', 'ấ': 'а', 'ẫ': 'а',
        'ậ': 'а', 'ä': 'а', 'å': 'а', 'ȧ': 'а', 'ǎ': 'а', 'ȁ': 'а',
        # О/о варианты
        'ȯ': 'о', 'ο': 'о', 'о': 'о', 'ọ': 'о', 'ỏ': 'о', 'õ': 'о',
        'ō': 'о', 'ŏ': 'о', 'ö': 'о', 'ő': 'о', 'ô': 'о', 'ồ': 'о',
        'ố': 'о', 'ỗ': 'о', 'ộ': 'о', 'ơ': 'о', 'ờ': 'о', 'ớ': 'о',
        'ở': 'о', 'ỡ': 'о', 'ợ': 'о', 'ǒ': 'о', 'ȍ': 'о', '๐': 'о',
        # Е/е варианты
        'ε': 'е', 'е': 'е', 'ẹ': 'е', 'ẻ': 'е', 'ẽ': 'е', 'ē': 'е',
        'ĕ': 'е', 'ė': 'е', 'ë': 'е', 'ě': 'е', 'ȅ': 'е', 'ȩ': 'е',
        'ệ': 'е', 'ề': 'е', 'ế': 'е', 'ể': 'е', 'ễ': 'е', 'ə': 'е',
        # И/и варианты
        'і': 'и', 'ι': 'и', 'ї': 'и', 'ị': 'и', 'ỉ': 'и', 'ĩ': 'и',
        'ī': 'и', 'ĭ': 'и', 'ï': 'и', 'î': 'и', 'ǐ': 'и', 'ȉ': 'и',
        # У/у варианты
        'ü': 'у', 'ű': 'у', 'ù': 'у', 'ú': 'у', 'û': 'у', 'ũ': 'у',
        'ū': 'у', 'ŭ': 'у', 'ụ': 'у', 'ủ': 'у', 'ư': 'у', 'ừ': 'у',
        'ứ': 'у', 'ử': 'у', 'ữ': 'у', 'ự': 'у', 'ǔ': 'у', 'ȕ': 'у',
        # С/с варианты
        'ϲ': 'с', 'ҫ': 'с', 'ç': 'с', 'ć': 'с', 'ĉ': 'с', 'ċ': 'с', 'č': 'с',
        # Р/р варианты
        'ρ': 'р', 'р': 'р', 'ṕ': 'р', 'ṗ': 'р',
        # Н/н варианты
        'һ': 'н', 'ң': 'н', 'ℏ': 'н',
        # Т/т варианты
        'τ': 'т', 'ţ': 'т', 'ť': 'т', 'ṫ': 'т', 'ṭ': 'т',
        # В/в варианты
        'ʙ': 'в', 'ḃ': 'в', 'ḅ': 'в',
        # М/м варианты
        'м': 'м', 'ṁ': 'м', 'ṃ': 'м',
        # Другие
        'ḳ': 'к', 'ķ': 'к', 'ǩ': 'к',  # К
        'ẋ': 'х', 'ẍ': 'х',  # Х
        'ń': 'н', 'ņ': 'н', 'ň': 'н', 'ṅ': 'н', 'ṇ': 'н', 'ṉ': 'н',  # Н
        'ṡ': 'с', 'ṣ': 'с', 'ś': 'с', 'ŝ': 'с', 'š': 'с',  # С
        'ṙ': 'р', 'ṛ': 'р', 'ŕ': 'р', 'ř': 'р',  # Р
        # Ы варианты
        'ы': 'ы', 'ỵ': 'ы', 'ỷ': 'ы', 'ỹ': 'ы',
        # Б варианты (похожие на 6)
        '6': 'б',
        # Ь/ъ (мягкий/твёрдый знак через похожие)
        'ƅ': 'ь',
        # Л варианты
        'ḷ': 'л', 'ḹ': 'л', 'ļ': 'л', 'ľ': 'л',
        # Д варианты
        'ḋ': 'д', 'ḍ': 'д', 'ḏ': 'д', 'đ': 'д', 'ď': 'д',
        # Г варианты
        'ġ': 'г', 'ģ': 'г', 'ǧ': 'г', 'ǵ': 'г',
        # Ж варианты (через zh)
        'ʒ': 'ж', 'ž': 'ж', 'ż': 'ж',
        # З варианты
        'ẑ': 'з', 'ẓ': 'з', 'ź': 'з',
    }
    for homo, cyr in homoglyphs.items():
        text = text.replace(homo, cyr)

    # === ЭТАП 4: Удаление zero-width и невидимых символов ===
    zero_width = (
        '\u200b'  # Zero Width Space
        '\u200c'  # Zero Width Non-Joiner
        '\u200d'  # Zero Width Joiner
        '\u200e'  # Left-to-Right Mark
        '\u200f'  # Right-to-Left Mark
        '\u2060'  # Word Joiner
        '\u2061'  # Function Application
        '\u2062'  # Invisible Times
        '\u2063'  # Invisible Separator
        '\u2064'  # Invisible Plus
        '\u00ad'  # Soft Hyphen
        '\ufeff'  # Zero Width No-Break Space (BOM)
        '\u034f'  # Combining Grapheme Joiner
        '\u061c'  # Arabic Letter Mark
        '\u115f'  # Hangul Choseong Filler
        '\u1160'  # Hangul Jungseong Filler
        '\u17b4'  # Khmer Vowel Inherent Aq
        '\u17b5'  # Khmer Vowel Inherent Aa
        '\u180e'  # Mongolian Vowel Separator
        '\u2800'  # Braille Pattern Blank
        '\u3164'  # Hangul Filler
        '\uffa0'  # Halfwidth Hangul Filler
    )
    for char in zero_width:
        text = text.replace(char, '')

    # === ЭТАП 5: Удаление combining marks (диакритических знаков) ===
    # Спамеры добавляют их для обхода: з̧а̊р̀а̧б̱о̫т̰о̷к
    text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')

    # === ЭТАП 6: Удаление пробелов между одиночными буквами ===
    # "з а р а б о т о к" → "заработок"
    # Паттерн: буква + пробел + буква + пробел... (минимум 3 буквы через пробелы)
    def collapse_spaced_letters(t):
        # Ищем последовательности: буква пробел буква пробел буква...
        pattern = r'(?<!\S)([а-яёa-z])\s+(?=[а-яёa-z]\s*[а-яёa-z])'
        # Убираем пробелы между одиночными буквами
        result = re.sub(r'\b([а-яёa-z])\s+([а-яёa-z])\s+([а-яёa-z])', r'\1\2\3', t)
        # Повторяем несколько раз для длинных последовательностей
        for _ in range(5):
            new_result = re.sub(r'\b([а-яёa-z])\s+([а-яёa-z])\b', r'\1\2', result)
            if new_result == result:
                break
            result = new_result
        return result

    text = collapse_spaced_letters(text)

    # === ЭТАП 7: Склеивание разбитых спам-слов ===
    # Спамеры разбивают слова пробелами: "за работок" → "заработок"
    split_word_fixes = [
        # Заработок и производные
        (r'\bза\s+работ', 'заработ'),
        (r'\bза\s+рабат', 'зарабат'),
        (r'\bза\s+рплат', 'зарплат'),
        (r'\bза\s+рабо', 'зарабо'),
        # Подработка
        (r'\bпод\s+работ', 'подработ'),
        (r'\bпод\s+рабо', 'подрабо'),
        # Доход
        (r'\bдо\s+ход', 'доход'),
        # Оплата
        (r'\bо\s+плат', 'оплат'),
        (r'\bоп\s+лат', 'оплат'),
        # Работа
        (r'\bра\s+бот', 'работ'),
        (r'\bраб\s+от', 'работ'),
        # Деньги
        (r'\bде\s+ньг', 'деньг'),
        (r'\bден\s+ьг', 'деньг'),
        # Криптa
        (r'\bкри\s+пт', 'крипт'),
        (r'\bкрип\s+т', 'крипт'),
        # Инвестиции
        (r'\bин\s+вест', 'инвест'),
        # Казино
        (r'\bка\s+зин', 'казин'),
        # Эскорт
        (r'\bэс\s+корт', 'эскорт'),
        # Интим
        (r'\bин\s+тим', 'интим'),
    ]
    for pattern, replacement in split_word_fixes:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)

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

        # Аудит лог
        audit_logger.log_user_banned(user_id, chat_id, reason)

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
    user_name = message.from_user.full_name or message.from_user.username

    # Тестер или Админ - УДАЛЯЕМ сообщение, но БЕЗ предупреждений и бана
    if user_id in TESTER_IDS or user_id in ADMIN_IDS:
        role = "ADMIN" if user_id in ADMIN_IDS else "TESTER"
        role_label = "админ" if user_id in ADMIN_IDS else "тестер"

        try:
            await message.delete()
            stats["spam_deleted"] += 1
        except Exception as e:
            logger.warning(f"[{role}] Failed to delete message: {e}")

        test_msg = await message.answer(
            f"🧪 <b>ТЕСТ-РЕЖИМ</b>\n\n"
            f"Спам удалён: <i>{reason}</i>\n"
            f"Уверенность: {confidence:.0%}\n\n"
            f"<i>Без предупреждения (вы {role_label})</i>",
            parse_mode="HTML"
        )
        await asyncio.sleep(10)
        try:
            await test_msg.delete()
        except:
            pass
        logger.info(f"[{role}] Spam DELETED from {user_name} ({user_id}): {reason} [{confidence:.0%}]")
        return

    try:
        # Удаляем сообщение
        await message.delete()
        stats["spam_deleted"] += 1
        behavior_analyzer.record_spam(user_id)

        # Добавляем предупреждение
        warnings = storage.add_warning(user_id)

        # Аудит лог
        text = message.text or message.caption or ""
        audit_logger.log_spam_detected(
            user_id, chat_id, text, confidence, reason.split(', ')
        )

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

    # Тестеры - показываем верификацию, но НЕ ограничиваем
    is_tester = user.id in TESTER_IDS

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
        # Аудит лог
        audit_logger.log_security_event(
            "RAID_DETECTED",
            user_id=user.id,
            chat_id=chat_id,
            details=f"joins_per_min={raid_detector.get_join_rate(chat_id)}"
        )
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
        # Ограничиваем права (кроме тестеров)
        if not is_tester:
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
        tester_note = "\n\n🧪 <i>(Тестовый режим - вы НЕ ограничены)</i>" if is_tester else ""
        msg = await bot.send_message(
            chat_id=chat_id,
            text=(
                f"🎙 <b>Привет, {user_name}!</b>\n\n"
                f"{CHAT_RULES}\n"
                f"⏰ Нажми кнопку ниже в течение {VERIFY_TIMEOUT} секунд, "
                f"чтобы присоединиться к нашей музыкальной семье!{tester_note}"
            ),
            reply_markup=get_verify_keyboard(user.id),
            parse_mode="HTML"
        )

        # Тестеров не кикаем по таймауту
        if not is_tester:
            task = asyncio.create_task(kick_unverified(user.id, chat_id, msg.message_id))
        else:
            task = None
            logger.info(f"[TESTER] User {user.id} is tester, will not be kicked")

        pending_verification[user.id] = {
            "chat_id": chat_id,
            "message_id": msg.message_id,
            "task": task,
            "is_tester": is_tester
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
        is_tester = user_id in TESTER_IDS

        if user_id in pending_verification:
            task = pending_verification[user_id].get("task")
            if task:  # Для тестеров task может быть None
                task.cancel()
            pending_verification.pop(user_id, None)

        # Для новичков - ограниченные права (нельзя ссылки/форварды)
        # Тестерам не ограничиваем
        if not is_tester:
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

        # Аудит лог
        audit_logger.log_user_verified(user_id, callback.message.chat.id)

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
    # Админы и тестеры проверяются, но без последствий (в process_spam_message)

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
                is_verified = message.from_user.id in verified_users
                is_spam, confidence, triggered = ml_classifier.classify(
                    features, is_newbie=is_newbie, is_night=is_night, is_verified=is_verified
                )

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
    # Админы и тестеры проверяются, но без последствий (в process_spam_message)

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
    # Админы и тестеры проверяются, но без последствий (в process_spam_message)

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
    is_tester = user_id in TESTER_IDS
    is_admin = user_id in ADMIN_IDS
    is_privileged = is_tester or is_admin  # Тестеры и админы - привилегированные

    # Записываем активность
    behavior_analyzer.record_message(user_id)

    user_profile = behavior_analyzer.get_profile(user_id)
    is_newbie = behavior_analyzer.is_newbie(user_id)
    is_night = is_night_mode()
    text_has_links = has_links(text)

    # Проверка cooldown для новичков (тестеры/админы видят предупреждение, но не блокируются)
    if is_newbie and not is_privileged:
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
    elif is_newbie and is_privileged:
        # Тестер/админ-новичок - показываем что сработало бы
        can_send, seconds_left = behavior_analyzer.check_newbie_cooldown(user_id)
        if not can_send:
            role = "админ" if is_admin else "тестер"
            warn_msg = await message.reply(
                f"🧪 <b>ТЕСТ:</b> Slow mode ({seconds_left} сек.) — сообщение НЕ удалено (вы {role})",
                parse_mode="HTML"
            )
            await asyncio.sleep(5)
            try:
                await warn_msg.delete()
            except:
                pass
        behavior_analyzer.record_newbie_message(user_id)

    # Ограничение ссылок для новичков
    if is_newbie and text_has_links:
        if is_privileged:
            role = "админ" if is_admin else "тестер"
            warn_msg = await message.reply(
                f"🧪 <b>ТЕСТ:</b> Ссылки для новичков запрещены — сообщение НЕ удалено (вы {role})",
                parse_mode="HTML"
            )
            await asyncio.sleep(5)
            try:
                await warn_msg.delete()
            except:
                pass
        else:
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
    is_verified = user_id in verified_users
    is_spam, confidence, triggered = ml_classifier.classify(
        features, is_newbie=is_newbie, is_night=is_night, is_verified=is_verified
    )

    # DEBUG: Логируем для админов/тестеров
    if is_privileged:
        normalized = normalize_text(text)
        threshold = ml_classifier.get_dynamic_threshold(is_newbie, is_night, is_verified)
        logger.info(f"[DEBUG] Original: {repr(text)}")
        logger.info(f"[DEBUG] Normalized: {repr(normalized)}")
        logger.info(f"[DEBUG] Score: {confidence:.2f}, Threshold: {threshold:.2f}, Spam: {is_spam}, Triggered: {triggered}")
        top_features = {k: v for k, v in features.items() if v > 0}
        logger.info(f"[DEBUG] Active features: {top_features}")

    if is_spam:
        reason = ', '.join(triggered[:3]) if triggered else "подозрительное сообщение"
        await process_spam_message(message, reason, confidence)


# ============== КОМАНДЫ АДМИНИСТРАТОРА ==============

@router.message(Command("spam_stats"))
async def cmd_stats(message: Message):
    """Статистика бота"""
    if message.from_user.id not in ADMIN_IDS and message.from_user.id not in TESTER_IDS:
        return

    uptime = datetime.now() - stats["start_time"]
    hours = int(uptime.total_seconds() // 3600)
    minutes = int((uptime.total_seconds() % 3600) // 60)

    night_status = "🌙 АКТИВЕН" if is_night_mode() else "☀️ неактивен"
    lockdown_status = "🔴 АКТИВЕН" if raid_detector.is_lockdown() else "🟢 неактивен"

    await message.answer(
        f"🎙 <b>БИМ радио — Статистика v{BOT_VERSION}</b>\n\n"
        f"📦 Деплой: {DEPLOY_TIME}\n"
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
    if message.from_user.id not in ADMIN_IDS and message.from_user.id not in TESTER_IDS:
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
    if message.from_user.id not in ADMIN_IDS and message.from_user.id not in TESTER_IDS:
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


@router.message(Command("spam_check"))
async def cmd_check_user(message: Message):
    """Полная проверка пользователя — все данные в одном месте"""
    if message.from_user.id not in ADMIN_IDS and message.from_user.id not in TESTER_IDS:
        return

    # Получаем user_id из реплая или аргумента
    target_user_id = None
    target_name = "Неизвестно"

    if message.reply_to_message:
        target_user_id = message.reply_to_message.from_user.id
        target_name = message.reply_to_message.from_user.full_name
    else:
        args = message.text.split()
        if len(args) >= 2:
            try:
                target_user_id = int(args[1])
            except ValueError:
                await message.answer("❌ Неверный ID. Используйте: /spam_check <user_id> или реплай на сообщение")
                return
        else:
            await message.answer(
                "🔍 <b>Проверка пользователя</b>\n\n"
                "Использование:\n"
                "• /spam_check <user_id>\n"
                "• Реплай на сообщение + /spam_check",
                parse_mode="HTML"
            )
            return

    # Собираем всю информацию
    warnings = storage.get_warnings(target_user_id)
    is_banned = storage.is_banned(target_user_id)
    is_whitelisted = storage.is_whitelisted(target_user_id)
    is_verified = target_user_id in verified_users
    is_admin = target_user_id in ADMIN_IDS
    is_tester = target_user_id in TESTER_IDS

    profile = behavior_analyzer.get_profile(target_user_id)
    is_newbie = behavior_analyzer.is_newbie(target_user_id)

    # Время в чате
    hours_in_chat = (datetime.now() - profile.join_time).total_seconds() / 3600

    # CAS проверка
    is_cas = await cas_checker.check(target_user_id)

    # Формируем статусы
    statuses = []
    if is_admin:
        statuses.append("👑 Админ")
    if is_tester:
        statuses.append("🧪 Тестер")
    if is_whitelisted:
        statuses.append("✅ Whitelist")
    if is_banned:
        statuses.append("⛔️ Забанен")
    if is_cas:
        statuses.append("🛡 CAS-бан")
    if is_verified:
        statuses.append("✓ Верифицирован")
    if is_newbie:
        statuses.append("🆕 Новичок")

    status_line = " | ".join(statuses) if statuses else "Обычный пользователь"

    report = (
        f"🔍 <b>Проверка пользователя</b>\n\n"
        f"👤 ID: <code>{target_user_id}</code>\n"
        f"📛 Имя: {target_name}\n\n"
        f"<b>Статус:</b> {status_line}\n\n"
        f"<b>Данные:</b>\n"
        f"⚠️ Предупреждений: {warnings}/{MAX_WARNINGS}\n"
        f"📊 Спам-скор: {profile.spam_score:.2f}\n"
        f"💬 Сообщений: {profile.message_count}\n"
        f"🗑 Удалено: {profile.messages_deleted}\n"
        f"⏱ В чате: {hours_in_chat:.1f}ч\n"
    )

    await message.answer(report, parse_mode="HTML")


@router.message(Command("spam_unban"))
async def cmd_unban(message: Message):
    """Разбанить пользователя"""
    if message.from_user.id not in ADMIN_IDS and message.from_user.id not in TESTER_IDS:
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
    if message.from_user.id not in ADMIN_IDS and message.from_user.id not in TESTER_IDS:
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
    if message.from_user.id not in ADMIN_IDS and message.from_user.id not in TESTER_IDS:
        return

    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Использование: /spam_test <текст для проверки>")
        return

    test_text = args[1]

    # Создаём фейковый профиль для теста
    fake_profile = UserProfile(user_id=0)

    # Извлекаем признаки
    is_night = is_night_mode()
    features = ml_classifier.extract_features(
        test_text, fake_profile,
        is_newbie=True, is_night=is_night,
        has_link=has_links(test_text), is_cas_banned=False
    )

    # Тестируем как новичка (строгий режим)
    is_spam_result, confidence, triggered = ml_classifier.classify(
        features, is_newbie=True, is_night=is_night, is_verified=False
    )
    threshold = ml_classifier.get_dynamic_threshold(is_newbie=True, is_night=is_night, is_verified=False)

    # Проверка на мат
    has_profanity = check_profanity(test_text)

    # Формируем отчёт
    result = "🚫 <b>СПАМ</b>" if is_spam_result else "✅ <b>Чисто</b>"

    report = (
        f"🔍 <b>Результат проверки:</b>\n\n"
        f"📝 Текст: <code>{test_text[:100]}{'...' if len(test_text) > 100 else ''}</code>\n\n"
        f"{result} (score: {confidence:.0%}, порог: {threshold:.0%})\n\n"
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
    if message.from_user.id not in ADMIN_IDS and message.from_user.id not in TESTER_IDS:
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
    if message.from_user.id not in ADMIN_IDS and message.from_user.id not in TESTER_IDS:
        return

    await message.answer(
        f"🎙 <b>БИМ радио — Команды антиспам бота v{BOT_VERSION}</b>\n\n"
        "<b>📊 Статистика:</b>\n"
        "/spam_stats — статистика бота\n\n"
        "<b>🔍 Проверка:</b>\n"
        "/spam_test <текст> — проверить текст на спам\n"
        "/spam_check <id> — полная проверка юзера\n\n"
        "<b>📝 Управление:</b>\n"
        "/spam_add <слово> — добавить стоп-слово\n"
        "/spam_whitelist — управление whitelist\n"
        "/spam_warn <id> — проверить предупреждения\n"
        "/spam_unban <id> — разбанить пользователя\n\n"
        "<b>🚨 Антирейд:</b>\n"
        "/spam_lockdown — управление блокировкой\n"
        "/spam_reset — сбросить свой профиль (после тестов)\n\n"
        "<b>🛡 Возможности:</b>\n"
        "• Верификация с правилами БИМ радио\n"
        "• CAS (Combot Anti-Spam)\n"
        "• Детекция 18+ спама и переманок\n"
        "• Авто-бан после 5 предупреждений\n"
        "• Ночной режим (23:00-07:00)\n"
        "• Антирейд защита\n"
        "• ML классификатор спама\n"
        "• Мат-фильтр",
        parse_mode="HTML"
    )


@router.message(Command("spam_reset"))
async def cmd_reset_profile(message: Message):
    """Сбросить свой spam профиль (для тестеров/админов)"""
    user_id = message.from_user.id

    if user_id not in ADMIN_IDS and user_id not in TESTER_IDS:
        return

    # Сбрасываем профиль
    if user_id in behavior_analyzer.profiles:
        del behavior_analyzer.profiles[user_id]

    # Сбрасываем предупреждения
    if user_id in storage.warnings:
        del storage.warnings[user_id]
        storage._save()

    # Удаляем из message_times и newbie_messages
    behavior_analyzer.message_times.pop(user_id, None)
    behavior_analyzer.newbie_messages.pop(user_id, None)

    await message.answer(
        "✅ <b>Профиль сброшен!</b>\n\n"
        "• spam_score: 0\n"
        "• warnings: 0\n"
        "• message_count: 0\n\n"
        "Теперь ты чист 🧹",
        parse_mode="HTML"
    )
    logger.info(f"Profile reset for user {user_id}")


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

            # Очистка user profiles для предотвращения утечки памяти
            cleaned_profiles = behavior_analyzer.cleanup_old_profiles()
            if cleaned_profiles > 0:
                logger.info(f"Cleaned {cleaned_profiles} old user profiles")

            # Ограничение размера verified_users
            global verified_users
            if len(verified_users) > MAX_VERIFIED_USERS:
                # Нельзя определить "старых" пользователей в set, просто обрезаем
                # В реальности это редко случается
                excess = len(verified_users) - MAX_VERIFIED_USERS
                logger.warning(f"verified_users overflow! Removing {excess} entries")
                # Конвертируем в список, удаляем первые N, конвертируем обратно
                users_list = list(verified_users)
                verified_users = set(users_list[excess:])

            logger.info(f"Auto-cleanup completed. Profiles: {len(behavior_analyzer.profiles)}, Verified: {len(verified_users)}")

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
    logger.info(f"Starting spam filter bot v{BOT_VERSION}...")
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
