# Message Collector Bot

Telegram бот для сбора сообщений от аудитории. Люди пишут боту, сообщения пересылаются в твой приватный канал с удобным форматированием и кнопками.

## Возможности

- Приём текстовых сообщений, фото, видео, голосовых, документов
- Пересылка в приватный канал с информацией об отправителе
- Кнопки "В избранное" и "Скрыть" под каждым сообщением
- Команды `/starred` и `/stats` для админа
- Автоответ отправителям

## Установка

### 1. Создай бота

1. Напиши [@BotFather](https://t.me/BotFather) в Telegram
2. Отправь `/newbot`
3. Задай имя и username бота
4. Скопируй токен (выглядит как `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`)

### 2. Создай приватный канал

1. Создай новый канал в Telegram (приватный)
2. Добавь своего бота в канал как администратора (с правом публикации)
3. Узнай ID канала:
   - Добавь [@getmyid_bot](https://t.me/getmyid_bot) в канал
   - Он напишет ID канала (формат: `-100xxxxxxxxxx`)
   - Удали бота из канала

### 3. Узнай свой Telegram ID

Напиши [@getmyid_bot](https://t.me/getmyid_bot) — он покажет твой ID.

### 4. Настрой переменные окружения

```bash
cp .env.example .env
```

Отредактируй `.env`:

```env
BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
CHANNEL_ID=-1001234567890
ADMIN_ID=123456789
```

### 5. Установи зависимости

```bash
pip install -r requirements.txt
```

### 6. Запусти бота

```bash
python bot.py
```

## Использование

### Для аудитории

Люди переходят по ссылке `t.me/username_бота` и пишут сообщения. Бот отвечает "Спасибо, сообщение получено".

### Для админа

В канале под каждым сообщением кнопки:
- **⭐ В избранное** — пометить интересное сообщение
- **🗑 Скрыть** — удалить сообщение из канала

Команды в боте (только для админа):
- `/starred` — показать все избранные сообщения
- `/stats` — статистика (всего сообщений, за сегодня, за неделю)

## Структура проекта

```
├── bot.py           # Основной код бота
├── config.py        # Конфигурация
├── database.py      # Работа с SQLite
├── requirements.txt # Зависимости
├── .env.example     # Пример переменных окружения
└── README.md        # Документация
```

## Запуск на сервере (постоянная работа)

### Через systemd (Linux)

Создай файл `/etc/systemd/system/message-bot.service`:

```ini
[Unit]
Description=Message Collector Telegram Bot
After=network.target

[Service]
Type=simple
User=your_user
WorkingDirectory=/path/to/bot
ExecStart=/usr/bin/python3 bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Затем:

```bash
sudo systemctl daemon-reload
sudo systemctl enable message-bot
sudo systemctl start message-bot
```

### Через Docker

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["python", "bot.py"]
```

```bash
docker build -t message-bot .
docker run -d --env-file .env message-bot
```
