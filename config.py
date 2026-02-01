import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))

# Поддержка нескольких админов
_admin_ids_str = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = [int(x.strip()) for x in _admin_ids_str.split(",") if x.strip()]

# Путь к базе данных
DATABASE_PATH = "messages.db"

# Текст автоответа отправителю
AUTO_REPLY_TEXT = "✅ Спасибо! Ваше сообщение получено."
