import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# Путь к базе данных
DATABASE_PATH = "messages.db"

# Текст автоответа отправителю
AUTO_REPLY_TEXT = "✅ Спасибо! Ваше сообщение получено."
