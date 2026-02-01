import aiosqlite
from datetime import datetime
from config import DATABASE_PATH


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
                is_starred INTEGER DEFAULT 0,
                is_hidden INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
    has_photo: bool = False
) -> int:
    """Сохранить сообщение в БД"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            """
            INSERT INTO messages
            (telegram_message_id, channel_message_id, user_id, username, full_name, text, has_photo)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (telegram_message_id, channel_message_id, user_id, username, full_name, text, int(has_photo))
        )
        await db.commit()
        return cursor.lastrowid


async def toggle_starred(message_db_id: int) -> bool:
    """Переключить статус избранного, вернуть новый статус"""
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
    """Переключить статус скрытого, вернуть новый статус"""
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
        cursor = await db.execute("SELECT COUNT(*) FROM messages WHERE is_starred = 1")
        starred = (await cursor.fetchone())[0]

        # Уникальных пользователей
        cursor = await db.execute("SELECT COUNT(DISTINCT user_id) FROM messages")
        unique_users = (await cursor.fetchone())[0]

        return {
            "total": total,
            "today": today,
            "week": week,
            "starred": starred,
            "unique_users": unique_users
        }


async def get_message_by_channel_id(channel_message_id: int):
    """Найти сообщение по ID в канале"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM messages WHERE channel_message_id = ?",
            (channel_message_id,)
        )
        return await cursor.fetchone()
