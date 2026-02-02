import asyncio
import logging
import json
import os
from datetime import datetime

from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter

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

# Версия бота и время запуска
VERSION = "3.4"
BOT_START_TIME = datetime.now()
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


def format_uptime() -> str:
    """Форматировать время работы бота"""
    delta = datetime.now() - BOT_START_TIME
    days = delta.days
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    if days > 0:
        return f"{days}д {hours}ч {minutes}мин"
    elif hours > 0:
        return f"{hours}ч {minutes}мин"
    else:
        return f"{minutes}мин {seconds}сек"


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


async def create_excel_export(messages: list, stats: dict) -> str:
    """Создать профессиональный Excel отчёт для БИМ радио"""
    wb = Workbook()

    # ============ СТИЛИ ============
    # Цвета
    BLUE = "4472C4"
    GREEN = "70AD47"
    ORANGE = "ED7D31"
    PURPLE = "7030A0"
    RED = "C00000"
    YELLOW = "FFC000"

    header_font = Font(bold=True, color="FFFFFF", size=11)
    title_font = Font(bold=True, size=16, color="FFFFFF")
    big_number_font = Font(bold=True, size=28, color=BLUE)
    subtitle_font = Font(bold=True, size=12)
    header_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    center_align = Alignment(horizontal="center", vertical="center")

    thin_border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )

    # Заливки
    header_fill = PatternFill(start_color=BLUE, end_color=BLUE, fill_type="solid")
    green_fill = PatternFill(start_color=GREEN, end_color=GREEN, fill_type="solid")
    orange_fill = PatternFill(start_color=ORANGE, end_color=ORANGE, fill_type="solid")
    purple_fill = PatternFill(start_color=PURPLE, end_color=PURPLE, fill_type="solid")
    red_fill = PatternFill(start_color=RED, end_color=RED, fill_type="solid")
    yellow_fill = PatternFill(start_color=YELLOW, end_color=YELLOW, fill_type="solid")
    light_blue = PatternFill(start_color="DDEBF7", end_color="DDEBF7", fill_type="solid")
    light_green = PatternFill(start_color="E2EFDA", end_color="E2EFDA", fill_type="solid")
    light_yellow = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")
    light_red = PatternFill(start_color="FFCCCC", end_color="FFCCCC", fill_type="solid")
    zebra_fill = PatternFill(start_color="F2F2F2", end_color="F2F2F2", fill_type="solid")

    # ============ ПРЕДВАРИТЕЛЬНЫЙ АНАЛИЗ ДАННЫХ ============
    # Собираем аналитику по сообщениям
    hours_stats = {i: 0 for i in range(24)}
    days_stats = {i: 0 for i in range(7)}  # 0=пн, 6=вс
    days_names = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
    users_data = {}  # user_id -> {name, username, count, first_msg, last_msg}
    content_types = {"text": 0, "photo": 0, "voice": 0, "video": 0}
    priorities = {"high": 0, "medium": 0, "normal": 0}
    response_times = []  # минуты до ответа
    for_air = []  # сообщения для эфира
    needs_attention = []  # требуют внимания

    for msg in messages:
        # Парсим дату
        if isinstance(msg["created_at"], str):
            dt = datetime.fromisoformat(msg["created_at"])
        else:
            dt = msg["created_at"]

        # По часам
        hours_stats[dt.hour] += 1

        # По дням недели
        days_stats[dt.weekday()] += 1

        # По пользователям
        uid = msg["user_id"]
        if uid not in users_data:
            users_data[uid] = {
                "name": msg["full_name"],
                "username": msg["username"],
                "count": 0,
                "first_msg": dt,
                "last_msg": dt,
                "replied": 0
            }
        users_data[uid]["count"] += 1
        users_data[uid]["last_msg"] = max(users_data[uid]["last_msg"], dt)
        if msg["reply_text"]:
            users_data[uid]["replied"] += 1

        # Типы контента
        if msg.get("has_photo"):
            content_types["photo"] += 1
        elif msg.get("has_voice"):
            content_types["voice"] += 1
        elif msg.get("has_video"):
            content_types["video"] += 1
        else:
            content_types["text"] += 1

        # Приоритеты
        priority = detect_priority(msg["text"]) if msg["text"] else "normal"
        priorities[priority] += 1

        # Время ответа
        if msg.get("replied_at") and msg["created_at"]:
            try:
                created = datetime.fromisoformat(msg["created_at"]) if isinstance(msg["created_at"], str) else msg["created_at"]
                replied = datetime.fromisoformat(msg["replied_at"]) if isinstance(msg["replied_at"], str) else msg["replied_at"]
                diff_minutes = (replied - created).total_seconds() / 60
                if diff_minutes > 0:
                    response_times.append(diff_minutes)
            except:
                pass

        # Для эфира: избранные + длинные благодарности
        if msg["is_starred"]:
            for_air.append(msg)
        elif msg["category"] == "thanks" and msg["text"] and len(msg["text"]) > 100:
            for_air.append(msg)

        # Требуют внимания: непрочитанные + срочные
        if not msg["is_read"] or priority == "high":
            needs_attention.append(msg)

    # Расчёты
    total = len(messages)
    replied_count = stats.get("replied", 0)
    response_rate = (replied_count / total * 100) if total > 0 else 0
    avg_response_time = sum(response_times) / len(response_times) if response_times else 0
    new_users = sum(1 for u in users_data.values() if u["count"] == 1)
    returning_users = len(users_data) - new_users

    # Пиковый час
    peak_hour = max(hours_stats, key=hours_stats.get)
    peak_day = max(days_stats, key=days_stats.get)

    # ============ ЛИСТ 1: DASHBOARD ============
    ws = wb.active
    ws.title = "Dashboard"

    # Заголовок
    ws.merge_cells('A1:F1')
    ws['A1'] = "📻 АНАЛИТИКА БИМ РАДИО"
    ws['A1'].font = title_font
    ws['A1'].fill = header_fill
    ws['A1'].alignment = center_align

    ws.merge_cells('A2:F2')
    ws['A2'] = f"Период: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
    ws['A2'].alignment = center_align

    # KPI блоки (строка 4-6)
    kpi_data = [
        (total, "Всего сообщений", BLUE),
        (stats.get("today", 0), "Сегодня", GREEN),
        (f"{response_rate:.0f}%", "Отвечено", ORANGE),
        (stats.get("unread", 0), "Непрочитано", RED if stats.get("unread", 0) > 0 else GREEN),
        (priorities["high"], "Срочных", RED if priorities["high"] > 0 else GREEN),
        (len(users_data), "Слушателей", PURPLE),
    ]

    for col, (value, label, color) in enumerate(kpi_data, 1):
        # Значение
        cell = ws.cell(row=4, column=col, value=value)
        cell.font = big_number_font
        cell.alignment = center_align
        # Подпись
        cell = ws.cell(row=5, column=col, value=label)
        cell.font = subtitle_font
        cell.alignment = center_align
        ws.column_dimensions[get_column_letter(col)].width = 18

    # Секция: Эффективность (строка 8)
    ws['A8'] = "📈 ЭФФЕКТИВНОСТЬ"
    ws['A8'].font = subtitle_font
    ws.merge_cells('A8:B8')

    efficiency_data = [
        ("Среднее время ответа", f"{int(avg_response_time // 60)}ч {int(avg_response_time % 60)}мин" if avg_response_time else "—"),
        ("Ответов получено", f"{replied_count} из {total}"),
        ("Response Rate", f"{response_rate:.1f}%"),
    ]
    for i, (label, value) in enumerate(efficiency_data, 9):
        ws.cell(row=i, column=1, value=label).font = Font(bold=True)
        ws.cell(row=i, column=2, value=value)

    # Секция: Аудитория (строка 8, колонка D)
    ws['D8'] = "👥 АУДИТОРИЯ"
    ws['D8'].font = subtitle_font
    ws.merge_cells('D8:E8')

    audience_data = [
        ("Уникальных слушателей", len(users_data)),
        ("Новых (1 сообщение)", new_users),
        ("Постоянных (2+ сообщ.)", returning_users),
        ("Лояльных (5+ сообщ.)", sum(1 for u in users_data.values() if u["count"] >= 5)),
    ]
    for i, (label, value) in enumerate(audience_data, 9):
        ws.cell(row=i, column=4, value=label).font = Font(bold=True)
        ws.cell(row=i, column=5, value=value)

    # Секция: Активность по времени (строка 14)
    ws['A14'] = "🕐 ПИКИ АКТИВНОСТИ"
    ws['A14'].font = subtitle_font

    ws.cell(row=15, column=1, value="Самый активный час:")
    ws.cell(row=15, column=2, value=f"{peak_hour}:00 - {peak_hour+1}:00 ({hours_stats[peak_hour]} сообщ.)")
    ws.cell(row=16, column=1, value="Самый активный день:")
    ws.cell(row=16, column=2, value=f"{days_names[peak_day]} ({days_stats[peak_day]} сообщ.)")

    # Секция: Типы контента (строка 14, колонка D)
    ws['D14'] = "📎 ТИПЫ КОНТЕНТА"
    ws['D14'].font = subtitle_font

    content_row = 15
    for ctype, count in content_types.items():
        type_names = {"text": "Текст", "photo": "Фото", "voice": "Голосовые", "video": "Видео"}
        ws.cell(row=content_row, column=4, value=type_names[ctype])
        ws.cell(row=content_row, column=5, value=count)
        pct = (count / total * 100) if total > 0 else 0
        ws.cell(row=content_row, column=6, value=f"{pct:.1f}%")
        content_row += 1

    # Топ-5 слушателей (строка 20)
    ws['A20'] = "🏆 ТОП-5 АКТИВНЫХ СЛУШАТЕЛЕЙ"
    ws['A20'].font = subtitle_font
    ws.merge_cells('A20:C20')

    sorted_users = sorted(users_data.values(), key=lambda x: x["count"], reverse=True)[:5]
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
    for i, user in enumerate(sorted_users, 21):
        ws.cell(row=i, column=1, value=medals[i-21] if i-21 < 5 else "")
        ws.cell(row=i, column=2, value=user["name"])
        ws.cell(row=i, column=3, value=f"{user['count']} сообщ.")

    ws.freeze_panes = "A4"

    # ============ ЛИСТ 2: ВСЕ СООБЩЕНИЯ ============
    ws_msg = wb.create_sheet("Все сообщения")

    headers = [
        "№", "Дата", "Время", "День недели", "Час", "Имя", "Username", "User ID",
        "Сообщение", "Тип", "Категория", "Приоритет", "Статус",
        "Избранное", "Ответ", "Время ответа", "Ждёт ответа"
    ]

    for col, header in enumerate(headers, 1):
        cell = ws_msg.cell(row=1, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_alignment
        cell.border = thin_border

    for row_idx, msg in enumerate(messages, 2):
        if isinstance(msg["created_at"], str):
            dt = datetime.fromisoformat(msg["created_at"])
        else:
            dt = msg["created_at"]

        priority = detect_priority(msg["text"]) if msg["text"] else "normal"
        priority_text = {"high": "🔴 Срочно", "medium": "🟡 Средний", "normal": "🟢 Обычный"}[priority]

        category_text = CATEGORIES.get(msg["category"], "") if msg["category"] else "—"

        # Тип контента
        if msg.get("has_photo"):
            content_type = "📷 Фото"
        elif msg.get("has_voice"):
            content_type = "🎤 Голос"
        elif msg.get("has_video"):
            content_type = "🎬 Видео"
        else:
            content_type = "📝 Текст"

        # Статус
        if msg["reply_text"]:
            status = "✅ Отвечено"
        elif not msg["is_read"]:
            status = "🆕 Новое"
        else:
            status = "👁 Прочитано"

        # Время ответа
        response_time_str = ""
        if msg.get("replied_at"):
            try:
                created = datetime.fromisoformat(msg["created_at"]) if isinstance(msg["created_at"], str) else msg["created_at"]
                replied = datetime.fromisoformat(msg["replied_at"]) if isinstance(msg["replied_at"], str) else msg["replied_at"]
                diff = (replied - created).total_seconds() / 60
                if diff < 60:
                    response_time_str = f"{int(diff)} мин"
                else:
                    response_time_str = f"{int(diff//60)}ч {int(diff%60)}мин"
            except:
                pass

        # Время ожидания (если нет ответа)
        wait_time_str = ""
        if not msg["reply_text"]:
            diff = (datetime.now() - dt).total_seconds() / 60
            if diff < 60:
                wait_time_str = f"{int(diff)} мин"
            elif diff < 1440:
                wait_time_str = f"{int(diff//60)}ч {int(diff%60)}мин"
            else:
                wait_time_str = f"{int(diff//1440)}д {int((diff%1440)//60)}ч"

        row_data = [
            msg["id"],
            dt.strftime("%d.%m.%Y"),
            dt.strftime("%H:%M"),
            days_names[dt.weekday()],
            f"{dt.hour}:00",
            msg["full_name"],
            f"@{msg['username']}" if msg["username"] else "",
            msg["user_id"],
            msg["text"] or "[медиа]",
            content_type,
            category_text,
            priority_text,
            status,
            "⭐" if msg["is_starred"] else "",
            msg["reply_text"] or "",
            response_time_str,
            wait_time_str
        ]

        for col, value in enumerate(row_data, 1):
            cell = ws_msg.cell(row=row_idx, column=col, value=value)
            cell.border = thin_border
            cell.alignment = Alignment(vertical="top", wrap_text=(col == 9 or col == 15))

            # Подсветка по статусу
            if msg["is_starred"]:
                cell.fill = light_yellow
            elif priority == "high":
                cell.fill = light_red
            elif not msg["is_read"]:
                cell.fill = light_green
            elif msg["reply_text"]:
                cell.fill = light_blue
            elif row_idx % 2 == 0:
                cell.fill = zebra_fill

    column_widths = [6, 11, 7, 12, 6, 18, 15, 11, 45, 10, 15, 12, 12, 8, 35, 12, 12]
    for col, width in enumerate(column_widths, 1):
        ws_msg.column_dimensions[get_column_letter(col)].width = width

    ws_msg.freeze_panes = "A2"
    ws_msg.auto_filter.ref = f"A1:Q{len(messages)+1}"

    # ============ ЛИСТ 3: ДИНАМИКА ============
    ws_dyn = wb.create_sheet("Динамика")

    # По часам
    ws_dyn['A1'] = "🕐 АКТИВНОСТЬ ПО ЧАСАМ"
    ws_dyn['A1'].font = subtitle_font
    ws_dyn.merge_cells('A1:C1')

    ws_dyn.cell(row=2, column=1, value="Час").font = header_font
    ws_dyn.cell(row=2, column=1).fill = header_fill
    ws_dyn.cell(row=2, column=2, value="Сообщений").font = header_font
    ws_dyn.cell(row=2, column=2).fill = header_fill
    ws_dyn.cell(row=2, column=3, value="График").font = header_font
    ws_dyn.cell(row=2, column=3).fill = header_fill

    max_hour_count = max(hours_stats.values()) if hours_stats.values() else 1
    for i, hour in enumerate(range(24), 3):
        ws_dyn.cell(row=i, column=1, value=f"{hour:02d}:00")
        ws_dyn.cell(row=i, column=2, value=hours_stats[hour])
        # Визуальный график
        bar_len = int((hours_stats[hour] / max_hour_count) * 20) if max_hour_count > 0 else 0
        ws_dyn.cell(row=i, column=3, value="█" * bar_len)
        if hour == peak_hour:
            ws_dyn.cell(row=i, column=1).fill = light_yellow
            ws_dyn.cell(row=i, column=2).fill = light_yellow
            ws_dyn.cell(row=i, column=3).fill = light_yellow

    # По дням недели
    ws_dyn['E1'] = "📅 АКТИВНОСТЬ ПО ДНЯМ НЕДЕЛИ"
    ws_dyn['E1'].font = subtitle_font
    ws_dyn.merge_cells('E1:G1')

    ws_dyn.cell(row=2, column=5, value="День").font = header_font
    ws_dyn.cell(row=2, column=5).fill = orange_fill
    ws_dyn.cell(row=2, column=6, value="Сообщений").font = header_font
    ws_dyn.cell(row=2, column=6).fill = orange_fill
    ws_dyn.cell(row=2, column=7, value="%").font = header_font
    ws_dyn.cell(row=2, column=7).fill = orange_fill

    for i, day in enumerate(range(7), 3):
        ws_dyn.cell(row=i, column=5, value=days_names[day])
        ws_dyn.cell(row=i, column=6, value=days_stats[day])
        pct = (days_stats[day] / total * 100) if total > 0 else 0
        ws_dyn.cell(row=i, column=7, value=f"{pct:.1f}%")
        if day == peak_day:
            ws_dyn.cell(row=i, column=5).fill = light_yellow
            ws_dyn.cell(row=i, column=6).fill = light_yellow
            ws_dyn.cell(row=i, column=7).fill = light_yellow

    ws_dyn.column_dimensions['A'].width = 8
    ws_dyn.column_dimensions['B'].width = 12
    ws_dyn.column_dimensions['C'].width = 25
    ws_dyn.column_dimensions['E'].width = 14
    ws_dyn.column_dimensions['F'].width = 12
    ws_dyn.column_dimensions['G'].width = 8

    # ============ ЛИСТ 4: СЛУШАТЕЛИ ============
    ws_users = wb.create_sheet("Слушатели")

    headers = ["№", "Имя", "Username", "Сообщений", "Ответов получено", "Первое сообщение", "Последнее", "Статус"]
    for col, header in enumerate(headers, 1):
        cell = ws_users.cell(row=1, column=col, value=header)
        cell.font = header_font
        cell.fill = purple_fill
        cell.alignment = header_alignment
        cell.border = thin_border

    sorted_users_full = sorted(users_data.items(), key=lambda x: x[1]["count"], reverse=True)
    medals = ["🥇", "🥈", "🥉"]

    for row_idx, (uid, user) in enumerate(sorted_users_full, 2):
        medal = medals[row_idx-2] if row_idx <= 4 else str(row_idx-1)

        # Статус пользователя
        if user["count"] >= 10:
            status = "💎 VIP"
        elif user["count"] >= 5:
            status = "⭐ Постоянный"
        elif user["count"] >= 2:
            status = "🔄 Возвращается"
        else:
            status = "🆕 Новый"

        row_data = [
            medal,
            user["name"],
            f"@{user['username']}" if user["username"] else "",
            user["count"],
            user["replied"],
            user["first_msg"].strftime("%d.%m.%Y"),
            user["last_msg"].strftime("%d.%m.%Y"),
            status
        ]

        for col, value in enumerate(row_data, 1):
            cell = ws_users.cell(row=row_idx, column=col, value=value)
            cell.border = thin_border
            if row_idx <= 4:
                cell.fill = light_yellow

    column_widths = [6, 20, 15, 12, 15, 14, 14, 14]
    for col, width in enumerate(column_widths, 1):
        ws_users.column_dimensions[get_column_letter(col)].width = width

    ws_users.freeze_panes = "A2"

    # ============ ЛИСТ 5: АНАЛИТИКА ============
    ws_analytics = wb.create_sheet("Аналитика")

    # Категории
    ws_analytics['A1'] = "🏷 ПО КАТЕГОРИЯМ"
    ws_analytics['A1'].font = subtitle_font

    ws_analytics.cell(row=2, column=1, value="Категория").font = header_font
    ws_analytics.cell(row=2, column=1).fill = green_fill
    ws_analytics.cell(row=2, column=2, value="Кол-во").font = header_font
    ws_analytics.cell(row=2, column=2).fill = green_fill
    ws_analytics.cell(row=2, column=3, value="%").font = header_font
    ws_analytics.cell(row=2, column=3).fill = green_fill

    row = 3
    for cat_key, count in stats.get("categories", {}).items():
        cat_name = CATEGORIES.get(cat_key, cat_key)
        ws_analytics.cell(row=row, column=1, value=cat_name)
        ws_analytics.cell(row=row, column=2, value=count)
        pct = (count / total * 100) if total > 0 else 0
        ws_analytics.cell(row=row, column=3, value=f"{pct:.1f}%")
        row += 1

    # Без категории
    no_cat = total - sum(stats.get("categories", {}).values())
    ws_analytics.cell(row=row, column=1, value="Без категории")
    ws_analytics.cell(row=row, column=2, value=no_cat)
    pct = (no_cat / total * 100) if total > 0 else 0
    ws_analytics.cell(row=row, column=3, value=f"{pct:.1f}%")

    # Приоритеты
    ws_analytics['E1'] = "⚡ ПО ПРИОРИТЕТАМ"
    ws_analytics['E1'].font = subtitle_font

    ws_analytics.cell(row=2, column=5, value="Приоритет").font = header_font
    ws_analytics.cell(row=2, column=5).fill = orange_fill
    ws_analytics.cell(row=2, column=6, value="Кол-во").font = header_font
    ws_analytics.cell(row=2, column=6).fill = orange_fill

    priority_names = {"high": "🔴 Срочные", "medium": "🟡 Средние", "normal": "🟢 Обычные"}
    row = 3
    for prio, count in priorities.items():
        ws_analytics.cell(row=row, column=5, value=priority_names[prio])
        ws_analytics.cell(row=row, column=6, value=count)
        row += 1

    ws_analytics.column_dimensions['A'].width = 20
    ws_analytics.column_dimensions['B'].width = 10
    ws_analytics.column_dimensions['C'].width = 8
    ws_analytics.column_dimensions['E'].width = 15
    ws_analytics.column_dimensions['F'].width = 10

    # ============ ЛИСТ 6: ДЛЯ ЭФИРА ============
    ws_air = wb.create_sheet("Для эфира")

    ws_air['A1'] = "🎤 ЛУЧШИЕ СООБЩЕНИЯ ДЛЯ ЭФИРА"
    ws_air['A1'].font = title_font
    ws_air['A1'].fill = orange_fill
    ws_air.merge_cells('A1:D1')

    headers = ["№", "От кого", "Сообщение", "Почему выбрано"]
    for col, header in enumerate(headers, 1):
        cell = ws_air.cell(row=2, column=col, value=header)
        cell.font = header_font
        cell.fill = orange_fill
        cell.border = thin_border

    for row_idx, msg in enumerate(for_air[:30], 3):  # Топ 30
        reason = "⭐ Избранное" if msg["is_starred"] else "💬 Тёплый отзыв"
        row_data = [
            row_idx - 2,
            msg["full_name"],
            msg["text"] or "[медиа]",
            reason
        ]
        for col, value in enumerate(row_data, 1):
            cell = ws_air.cell(row=row_idx, column=col, value=value)
            cell.border = thin_border
            cell.alignment = Alignment(vertical="top", wrap_text=(col == 3))

    ws_air.column_dimensions['A'].width = 5
    ws_air.column_dimensions['B'].width = 20
    ws_air.column_dimensions['C'].width = 60
    ws_air.column_dimensions['D'].width = 18

    # ============ ЛИСТ 7: ТРЕБУЮТ ВНИМАНИЯ ============
    ws_attention = wb.create_sheet("Требуют внимания")

    ws_attention['A1'] = "⚠️ ТРЕБУЮТ ВНИМАНИЯ"
    ws_attention['A1'].font = title_font
    ws_attention['A1'].fill = red_fill
    ws_attention.merge_cells('A1:E1')

    headers = ["№", "От кого", "Сообщение", "Приоритет", "Ждёт ответа"]
    for col, header in enumerate(headers, 1):
        cell = ws_attention.cell(row=2, column=col, value=header)
        cell.font = header_font
        cell.fill = red_fill
        cell.border = thin_border

    # Сортируем: сначала срочные, потом по времени ожидания
    sorted_attention = sorted(needs_attention, key=lambda x: (
        0 if detect_priority(x["text"]) == "high" else 1,
        x["created_at"]
    ))

    for row_idx, msg in enumerate(sorted_attention[:50], 3):
        if isinstance(msg["created_at"], str):
            dt = datetime.fromisoformat(msg["created_at"])
        else:
            dt = msg["created_at"]

        diff = (datetime.now() - dt).total_seconds() / 60
        if diff < 60:
            wait = f"{int(diff)} мин"
        elif diff < 1440:
            wait = f"{int(diff//60)}ч {int(diff%60)}мин"
        else:
            wait = f"{int(diff//1440)}д {int((diff%1440)//60)}ч"

        priority = detect_priority(msg["text"]) if msg["text"] else "normal"
        priority_text = {"high": "🔴 СРОЧНО", "medium": "🟡 Средний", "normal": "🟢 Обычный"}[priority]

        row_data = [
            msg["id"],
            msg["full_name"],
            (msg["text"] or "[медиа]")[:100] + ("..." if msg["text"] and len(msg["text"]) > 100 else ""),
            priority_text,
            wait
        ]
        for col, value in enumerate(row_data, 1):
            cell = ws_attention.cell(row=row_idx, column=col, value=value)
            cell.border = thin_border
            if priority == "high":
                cell.fill = light_red

    ws_attention.column_dimensions['A'].width = 6
    ws_attention.column_dimensions['B'].width = 20
    ws_attention.column_dimensions['C'].width = 50
    ws_attention.column_dimensions['D'].width = 14
    ws_attention.column_dimensions['E'].width = 14

    # Сохраняем файл
    filename = f"BIM_Radio_Report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    wb.save(filename)

    return filename


def get_export_format_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора формата экспорта"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Excel (красивый отчёт)", callback_data="export:excel")],
        [InlineKeyboardButton(text="📄 JSON (для разработчиков)", callback_data="export:json")],
        [InlineKeyboardButton(text="📊 Excel + 📄 JSON (оба)", callback_data="export:both")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu:back")],
    ])


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
            f"👋 <b>Панель управления</b> <code>v{VERSION}</code>\n\n"
            f"📨 Всего сообщений: <b>{stats['total']}</b>\n"
            f"🆕 Непрочитанных: <b>{stats['unread']}</b>\n"
            f"⭐ Избранных: <b>{stats['starred']}</b>\n"
            f"👥 Пользователей: <b>{stats['unique_users']}</b>\n"
            f"📅 Сегодня: <b>{stats['today']}</b>\n"
            f"⏱ Uptime: <b>{format_uptime()}</b>\n"
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
    """Кнопка экспорта - показать выбор формата"""
    if not is_admin(message.from_user.id):
        return

    stats = await get_stats()
    await message.answer(
        f"📦 <b>Экспорт данных БИМ радио</b>\n\n"
        f"📨 Сообщений для экспорта: <b>{stats['total']}</b>\n"
        f"👥 Пользователей: <b>{stats['unique_users']}</b>\n\n"
        f"Выбери формат:",
        parse_mode=ParseMode.HTML,
        reply_markup=get_export_format_keyboard()
    )


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


@dp.message(Command("ping"))
async def cmd_ping(message: Message):
    """Проверка здоровья бота"""
    if is_admin(message.from_user.id):
        stats = await get_stats()
        text = (
            f"🏓 <b>Pong!</b>\n\n"
            f"📻 БИМ Радио бот <code>v{VERSION}</code>\n"
            f"⏱ Uptime: <b>{format_uptime()}</b>\n"
            f"📨 Сообщений: <b>{stats['total']}</b>\n"
            f"🆕 Непрочитанных: <b>{stats['unread']}</b>\n"
            f"✅ Бот работает нормально!"
        )
    else:
        text = (
            f"🏓 <b>Pong!</b>\n\n"
            f"📻 БИМ Радио бот <code>v{VERSION}</code>\n"
            f"⏱ Uptime: <b>{format_uptime()}</b>\n"
            f"✅ Бот работает!"
        )
    await message.answer(text, parse_mode=ParseMode.HTML)


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
        f"👋 <b>Панель управления</b> <code>v{VERSION}</code>\n\n"
        f"📨 Всего сообщений: <b>{stats['total']}</b>\n"
        f"🆕 Непрочитанных: <b>{stats['unread']}</b>\n"
        f"⭐ Избранных: <b>{stats['starred']}</b>\n"
        f"👥 Пользователей: <b>{stats['unique_users']}</b>\n"
        f"📅 Сегодня: <b>{stats['today']}</b>\n"
        f"⏱ Uptime: <b>{format_uptime()}</b>\n"
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
    """Показать меню выбора формата экспорта"""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔️")
        return

    stats = await get_stats()
    await callback.message.edit_text(
        f"📦 <b>Экспорт данных БИМ радио</b>\n\n"
        f"📨 Сообщений для экспорта: <b>{stats['total']}</b>\n"
        f"👥 Пользователей: <b>{stats['unique_users']}</b>\n\n"
        f"Выбери формат:",
        parse_mode=ParseMode.HTML,
        reply_markup=get_export_format_keyboard()
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("export:"))
async def callback_export_format(callback: CallbackQuery):
    """Экспорт в выбранном формате"""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔️")
        return

    format_type = callback.data.split(":")[1]
    await callback.answer("📦 Готовлю экспорт...")

    messages = await export_messages()
    stats = await get_stats()

    if not messages:
        await callback.message.edit_text("📭 Нет сообщений для экспорта")
        return

    files_to_send = []
    files_to_delete = []

    # Excel
    if format_type in ("excel", "both"):
        excel_filename = await create_excel_export([dict(m) for m in messages], stats)
        files_to_send.append((excel_filename, f"📊 Excel: {len(messages)} сообщений, 4 листа"))
        files_to_delete.append(excel_filename)

    # JSON
    if format_type in ("json", "both"):
        export_data = []
        for msg in messages:
            export_data.append({
                "id": msg["id"],
                "user_id": msg["user_id"],
                "username": msg["username"],
                "full_name": msg["full_name"],
                "text": msg["text"],
                "has_photo": bool(msg["has_photo"]),
                "has_voice": bool(msg["has_voice"]),
                "has_video": bool(msg["has_video"]),
                "is_starred": bool(msg["is_starred"]),
                "is_read": bool(msg["is_read"]),
                "is_hidden": bool(msg["is_hidden"]),
                "category": msg["category"],
                "priority": detect_priority(msg["text"]) if msg["text"] else "normal",
                "created_at": msg["created_at"],
                "reply_text": msg["reply_text"],
                "replied_at": msg.get("replied_at"),
            })

        json_filename = f"bim_radio_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(json_filename, "w", encoding="utf-8") as f:
            json.dump({
                "export_date": datetime.now().isoformat(),
                "total_messages": len(export_data),
                "stats": {
                    "total": stats["total"],
                    "unread": stats["unread"],
                    "starred": stats["starred"],
                    "replied": stats["replied"],
                    "unique_users": stats["unique_users"],
                },
                "messages": export_data
            }, f, ensure_ascii=False, indent=2)

        files_to_send.append((json_filename, f"📄 JSON: {len(messages)} сообщений"))
        files_to_delete.append(json_filename)

    # Отправляем файлы
    for filename, caption in files_to_send:
        await callback.message.answer_document(
            FSInputFile(filename),
            caption=caption
        )

    # Удаляем временные файлы
    for filename in files_to_delete:
        os.remove(filename)

    # Обновляем сообщение
    format_name = {"excel": "Excel", "json": "JSON", "both": "Excel + JSON"}[format_type]
    await callback.message.edit_text(
        f"✅ <b>Экспорт завершён!</b>\n\n"
        f"📦 Формат: {format_name}\n"
        f"📨 Сообщений: {len(messages)}\n"
        f"📅 {datetime.now().strftime('%d.%m.%Y %H:%M')}",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📦 Ещё экспорт", callback_data="menu:export")],
            [InlineKeyboardButton(text="◀️ В меню", callback_data="menu:back")],
        ])
    )


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
    logger.info(f"🚀 БИМ Радио бот v{VERSION} запущен!")
    logger.info(f"📢 Канал: {CHANNEL_ID}")
    logger.info(f"👑 Админы: {ADMIN_IDS}")
    logger.info(f"🕐 Запуск: {BOT_START_TIME.strftime('%d.%m.%Y %H:%M:%S')}")
    logger.info("=" * 40)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
