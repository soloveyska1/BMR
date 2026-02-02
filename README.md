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

## Автоматический деплой (CI/CD)

Проект поддерживает автоматический деплой при каждом push в репозиторий.

### Быстрая настройка (5 минут)

#### 1. Настройка сервера (один раз)

```bash
# Скачать и запустить скрипт настройки
curl -sSL https://raw.githubusercontent.com/soloveyska1/BMR/main/deploy/setup-server.sh | bash
```

Или вручную:
```bash
cd ~/BMR
chmod +x deploy/setup-server.sh
./deploy/setup-server.sh
```

#### 2. Настройка GitHub Secrets

Перейди в **Settings > Secrets and variables > Actions** в репозитории и добавь:

| Secret | Описание | Пример |
|--------|----------|--------|
| `SERVER_HOST` | IP адрес сервера | `123.45.67.89` |
| `SERVER_USER` | Имя пользователя SSH | `ubuntu` |
| `SSH_PRIVATE_KEY` | Приватный SSH ключ | `-----BEGIN OPENSSH...` |
| `SERVER_PORT` | SSH порт (опционально) | `22` |
| `PROJECT_PATH` | Путь к проекту (опционально) | `~/BMR` |

#### 3. Генерация SSH ключа

```bash
# На своём компьютере
ssh-keygen -t ed25519 -C "github-actions-deploy"

# Скопировать публичный ключ на сервер
ssh-copy-id -i ~/.ssh/id_ed25519.pub user@your-server

# Содержимое приватного ключа добавить в GitHub Secret SSH_PRIVATE_KEY
cat ~/.ssh/id_ed25519
```

### Как это работает

1. Ты делаешь `git push` в ветку `main` или `master`
2. GitHub Actions автоматически:
   - Проверяет синтаксис Python
   - Подключается к серверу по SSH
   - Скачивает последние изменения
   - Перезапускает ботов

### Выбор метода деплоя

**Вариант A: Systemd (рекомендуется для VPS)**
- Используется workflow `deploy.yml`
- Легче в настройке
- Меньше ресурсов

**Вариант B: Docker**
- Используется workflow `deploy-docker.yml`
- Изоляция окружения
- Легче масштабировать

Для Docker деплоя отключи `deploy.yml` и включи `deploy-docker.yml` в `.github/workflows/`.

### Docker Compose

Запуск обоих ботов одной командой:

```bash
# Создать .env и spam_bot.env файлы
cp .env.example .env
cp spam_bot.env.example spam_bot.env
# Отредактировать с токенами

# Запустить
docker-compose up -d

# Посмотреть логи
docker-compose logs -f

# Остановить
docker-compose down
```

### Ручной деплой

Если нужно задеплоить вручную:

```bash
cd ~/BMR
./deploy/deploy.sh
```

### Просмотр логов

```bash
# Systemd
journalctl -u bmr-collector-bot -f
journalctl -u bmr-spam-bot -f

# Docker
docker-compose logs -f collector-bot
docker-compose logs -f spam-bot
```

### Структура CI/CD

```
deploy/
├── deploy.sh              # Скрипт деплоя
├── setup-server.sh        # Первоначальная настройка сервера
├── bmr-collector-bot.service  # Systemd unit (шаблон)
└── bmr-spam-bot.service       # Systemd unit (шаблон)

.github/workflows/
├── deploy.yml             # GitHub Actions (Systemd)
└── deploy-docker.yml      # GitHub Actions (Docker)
```
