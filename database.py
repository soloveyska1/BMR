import aiosqlite
from datetime import datetime, timedelta
from typing import Optional
from config import DATABASE_PATH


# ============== УРОВНИ СЛУШАТЕЛЕЙ ==============
LISTENER_LEVELS = {
    1: {"name": "🆕 Новичок", "min_messages": 0},
    2: {"name": "🔄 Постоянный", "min_messages": 3},
    3: {"name": "⭐ Активист", "min_messages": 10},
    4: {"name": "💎 VIP", "min_messages": 25},
    5: {"name": "👑 Легенда", "min_messages": 50},
}


def get_level_for_messages(message_count: int) -> int:
    """Определить уровень по количеству сообщений"""
    level = 1
    for lvl, data in LISTENER_LEVELS.items():
        if message_count >= data["min_messages"]:
            level = lvl
    return level


def get_level_info(level: int) -> dict:
    """Получить информацию об уровне"""
    return LISTENER_LEVELS.get(level, LISTENER_LEVELS[1])


async def init_db():
    """Инициализация базы данных"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_message_id INTEGER,
                channel_message_id INTEGER,
                user_id INTEGER,
                username TEXT,
                full_name TEXT,
                text TEXT,
                has_photo INTEGER DEFAULT 0,
                has_voice INTEGER DEFAULT 0,
                has_video INTEGER DEFAULT 0,
                is_starred INTEGER DEFAULT 0,
                is_hidden INTEGER DEFAULT 0,
                is_read INTEGER DEFAULT 0,
                category TEXT DEFAULT NULL,
                reply_text TEXT DEFAULT NULL,
                replied_at TIMESTAMP DEFAULT NULL,
                read_on_air INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Таблица слушателей
        await db.execute("""
            CREATE TABLE IF NOT EXISTS listeners (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                level INTEGER DEFAULT 1,
                total_messages INTEGER DEFAULT 0,
                first_message_at TIMESTAMP,
                last_message_at TIMESTAMP,
                on_air_count INTEGER DEFAULT 0,
                replies_received INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Очередь для эфира
        await db.execute("""
            CREATE TABLE IF NOT EXISTS on_air_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id INTEGER,
                user_id INTEGER,
                priority INTEGER DEFAULT 0,
                shoutout_type TEXT DEFAULT NULL,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.commit()


async def save_message(
    telegram_message_id: int,
    channel_message_id: int,
    user_id: int,
    username: str,
    full_name: str,
    text: str,
    has_photo: bool = False,
    has_voice: bool = False,
    has_video: bool = False
) -> int:
    """Сохранить сообщение в БД"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            """
            INSERT INTO messages
            (telegram_message_id, channel_message_id, user_id, username, full_name, text, has_photo, has_voice, has_video)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (telegram_message_id, channel_message_id, user_id, username, full_name, text,
             int(has_photo), int(has_voice), int(has_video))
        )
        await db.commit()
        return cursor.lastrowid


async def get_message_by_id(message_db_id: int):
    """Получить сообщение по ID в БД"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM messages WHERE id = ?", (message_db_id,)
        )
        return await cursor.fetchone()


async def toggle_starred(message_db_id: int) -> bool:
    """Переключить статус избранного"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            "SELECT is_starred FROM messages WHERE id = ?", (message_db_id,)
        )
        row = await cursor.fetchone()
        if not row:
            return False

        new_status = 0 if row[0] else 1
        await db.execute(
            "UPDATE messages SET is_starred = ? WHERE id = ?",
            (new_status, message_db_id)
        )
        await db.commit()
        return bool(new_status)


async def toggle_hidden(message_db_id: int) -> bool:
    """Переключить статус скрытого"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            "SELECT is_hidden FROM messages WHERE id = ?", (message_db_id,)
        )
        row = await cursor.fetchone()
        if not row:
            return False

        new_status = 0 if row[0] else 1
        await db.execute(
            "UPDATE messages SET is_hidden = ? WHERE id = ?",
            (new_status, message_db_id)
        )
        await db.commit()
        return bool(new_status)


async def mark_as_read(message_db_id: int):
    """Отметить сообщение как прочитанное"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "UPDATE messages SET is_read = 1 WHERE id = ?", (message_db_id,)
        )
        await db.commit()


async def set_category(message_db_id: int, category: str):
    """Установить категорию сообщения"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "UPDATE messages SET category = ? WHERE id = ?",
            (category, message_db_id)
        )
        await db.commit()


async def save_reply(message_db_id: int, reply_text: str):
    """Сохранить ответ на сообщение"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "UPDATE messages SET reply_text = ?, replied_at = ? WHERE id = ?",
            (reply_text, datetime.now().isoformat(), message_db_id)
        )
        await db.commit()


async def get_starred_messages(limit: int = 50):
    """Получить избранные сообщения"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT * FROM messages
            WHERE is_starred = 1 AND is_hidden = 0
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,)
        )
        return await cursor.fetchall()


async def get_unread_messages(limit: int = 50):
    """Получить непрочитанные сообщения"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT * FROM messages
            WHERE is_read = 0 AND is_hidden = 0
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,)
        )
        return await cursor.fetchall()


async def get_messages_by_category(category: str, limit: int = 50):
    """Получить сообщения по категории"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT * FROM messages
            WHERE category = ? AND is_hidden = 0
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (category, limit)
        )
        return await cursor.fetchall()


async def search_messages(query: str, limit: int = 20):
    """Поиск по сообщениям"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT * FROM messages
            WHERE (text LIKE ? OR full_name LIKE ? OR username LIKE ?)
            AND is_hidden = 0
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (f"%{query}%", f"%{query}%", f"%{query}%", limit)
        )
        return await cursor.fetchall()


async def get_stats():
    """Получить статистику"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        # Всего сообщений
        cursor = await db.execute("SELECT COUNT(*) FROM messages WHERE is_hidden = 0")
        total = (await cursor.fetchone())[0]

        # За сегодня
        cursor = await db.execute(
            "SELECT COUNT(*) FROM messages WHERE date(created_at) = date('now') AND is_hidden = 0"
        )
        today = (await cursor.fetchone())[0]

        # За неделю
        cursor = await db.execute(
            "SELECT COUNT(*) FROM messages WHERE created_at >= datetime('now', '-7 days') AND is_hidden = 0"
        )
        week = (await cursor.fetchone())[0]

        # Избранных
        cursor = await db.execute("SELECT COUNT(*) FROM messages WHERE is_starred = 1 AND is_hidden = 0")
        starred = (await cursor.fetchone())[0]

        # Непрочитанных
        cursor = await db.execute("SELECT COUNT(*) FROM messages WHERE is_read = 0 AND is_hidden = 0")
        unread = (await cursor.fetchone())[0]

        # Уникальных пользователей
        cursor = await db.execute("SELECT COUNT(DISTINCT user_id) FROM messages WHERE is_hidden = 0")
        unique_users = (await cursor.fetchone())[0]

        # С ответами
        cursor = await db.execute("SELECT COUNT(*) FROM messages WHERE reply_text IS NOT NULL AND is_hidden = 0")
        replied = (await cursor.fetchone())[0]

        # По категориям
        cursor = await db.execute("""
            SELECT category, COUNT(*) as cnt FROM messages
            WHERE category IS NOT NULL AND is_hidden = 0
            GROUP BY category
        """)
        categories = {row[0]: row[1] for row in await cursor.fetchall()}

        # Топ активных пользователей
        cursor = await db.execute("""
            SELECT full_name, username, COUNT(*) as cnt FROM messages
            WHERE is_hidden = 0
            GROUP BY user_id
            ORDER BY cnt DESC
            LIMIT 5
        """)
        top_users = await cursor.fetchall()

        return {
            "total": total,
            "today": today,
            "week": week,
            "starred": starred,
            "unread": unread,
            "unique_users": unique_users,
            "replied": replied,
            "categories": categories,
            "top_users": top_users
        }


async def export_messages(limit: int = 1000):
    """Экспорт сообщений"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT * FROM messages
            WHERE is_hidden = 0
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,)
        )
        return await cursor.fetchall()


async def get_message_by_channel_id(channel_message_id: int):
    """Найти сообщение по ID в канале"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM messages WHERE channel_message_id = ?",
            (channel_message_id,)
        )
        return await cursor.fetchone()


async def get_user_history(user_id: int, limit: int = 5):
    """Получить историю сообщений пользователя"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT * FROM messages
            WHERE user_id = ? AND is_hidden = 0
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (user_id, limit)
        )
        return await cursor.fetchall()


async def get_user_stats(user_id: int):
    """Получить статистику пользователя"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        # Всего сообщений
        cursor = await db.execute(
            "SELECT COUNT(*) FROM messages WHERE user_id = ? AND is_hidden = 0",
            (user_id,)
        )
        total = (await cursor.fetchone())[0]

        # Первое сообщение
        cursor = await db.execute(
            "SELECT created_at FROM messages WHERE user_id = ? ORDER BY created_at ASC LIMIT 1",
            (user_id,)
        )
        first_row = await cursor.fetchone()
        first_message = first_row[0] if first_row else None

        # Получено ответов
        cursor = await db.execute(
            "SELECT COUNT(*) FROM messages WHERE user_id = ? AND reply_text IS NOT NULL AND is_hidden = 0",
            (user_id,)
        )
        replied = (await cursor.fetchone())[0]

        return {
            "total": total,
            "first_message": first_message,
            "replied": replied
        }


# ============== ФУНКЦИИ ДЛЯ СЛУШАТЕЛЕЙ ==============

async def get_or_create_listener(user_id: int, username: str = None, full_name: str = None) -> dict:
    """Получить или создать профиль слушателя"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM listeners WHERE user_id = ?", (user_id,))
        row = await cursor.fetchone()

        if row:
            if username or full_name:
                await db.execute(
                    "UPDATE listeners SET username = COALESCE(?, username), full_name = COALESCE(?, full_name) WHERE user_id = ?",
                    (username, full_name, user_id)
                )
                await db.commit()
            return dict(row)

        now = datetime.now().isoformat()
        await db.execute(
            "INSERT INTO listeners (user_id, username, full_name, first_message_at, last_message_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, username, full_name, now, now)
        )
        await db.commit()

        cursor = await db.execute("SELECT * FROM listeners WHERE user_id = ?", (user_id,))
        return dict(await cursor.fetchone())


async def update_listener_activity(user_id: int, username: str = None, full_name: str = None) -> dict:
    """Обновить активность слушателя"""
    listener = await get_or_create_listener(user_id, username, full_name)
    now = datetime.now()

    new_total = listener["total_messages"] + 1
    new_level = get_level_for_messages(new_total)
    old_level = listener.get("level", 1)

    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "UPDATE listeners SET total_messages = ?, level = ?, last_message_at = ? WHERE user_id = ?",
            (new_total, new_level, now.isoformat(), user_id)
        )
        await db.commit()

    return {
        "level_up": new_level > old_level,
        "new_level": new_level,
        "total_messages": new_total
    }


async def get_listener_profile(user_id: int) -> Optional[dict]:
    """Получить профиль слушателя"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM listeners WHERE user_id = ?", (user_id,))
        row = await cursor.fetchone()
        if row:
            profile = dict(row)
            profile["level_info"] = get_level_info(profile.get("level", 1))
            return profile
        return None


# ============== ОЧЕРЕДЬ ДЛЯ ЭФИРА ==============

async def add_to_on_air_queue(message_id: int, user_id: int, shoutout_type: str = None) -> int:
    """Добавить в очередь для эфира"""
    listener = await get_listener_profile(user_id)
    priority = listener.get("level", 1) if listener else 1

    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO on_air_queue (message_id, user_id, priority, shoutout_type) VALUES (?, ?, ?, ?)",
            (message_id, user_id, priority, shoutout_type)
        )
        await db.commit()
        return cursor.lastrowid


async def get_on_air_queue(limit: int = 10) -> list:
    """Получить очередь для эфира"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT q.*, m.text, m.full_name, m.username, l.level
            FROM on_air_queue q
            JOIN messages m ON q.message_id = m.id
            LEFT JOIN listeners l ON q.user_id = l.user_id
            ORDER BY q.priority DESC, q.added_at ASC
            LIMIT ?
            """,
            (limit,)
        )
        return [dict(row) for row in await cursor.fetchall()]


async def remove_from_on_air_queue(queue_id: int):
    """Удалить из очереди"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("DELETE FROM on_air_queue WHERE id = ?", (queue_id,))
        await db.commit()


async def mark_as_read_on_air(message_id: int, user_id: int):
    """Отметить как прочитанное в эфире"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("UPDATE messages SET read_on_air = 1 WHERE id = ?", (message_id,))
        await db.execute("UPDATE listeners SET on_air_count = on_air_count + 1 WHERE user_id = ?", (user_id,))
        await db.commit()


# ============== СТАТИСТИКА ДЛЯ АДМИНОВ ==============

async def get_pending_messages_count(hours: int = 2) -> int:
    """Сообщения без ответа старше N часов"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM messages WHERE reply_text IS NULL AND is_hidden = 0 AND created_at < datetime('now', '-' || ? || ' hours')",
            (hours,)
        )
        return (await cursor.fetchone())[0]


async def get_daily_digest() -> dict:
    """Данные для ежедневного дайджеста"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM messages WHERE date(created_at) = date('now', '-1 day') AND is_hidden = 0")
        yesterday = (await cursor.fetchone())[0]

        cursor = await db.execute("SELECT COUNT(*) FROM messages WHERE is_read = 0 AND is_hidden = 0")
        unread = (await cursor.fetchone())[0]

        cursor = await db.execute("SELECT COUNT(*) FROM messages WHERE reply_text IS NULL AND is_hidden = 0 AND created_at < datetime('now', '-2 hours')")
        pending = (await cursor.fetchone())[0]

        cursor = await db.execute("SELECT COUNT(*) FROM listeners WHERE date(created_at) = date('now', '-1 day')")
        new_listeners = (await cursor.fetchone())[0]

        return {"yesterday": yesterday, "unread": unread, "pending": pending, "new_listeners": new_listeners}


async def get_top_listeners(limit: int = 5) -> list:
    """Топ слушателей"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM listeners ORDER BY total_messages DESC LIMIT ?", (limit,))
        return [dict(row) for row in await cursor.fetchall()]
