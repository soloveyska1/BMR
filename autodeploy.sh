#!/bin/bash
# Автодеплой spam_filter_bot.py
# Проверяет обновления каждую минуту и автоматически деплоит
# Ветка читается из конфиг-файла — автоматически обновляется

BOT_DIR="/root/spam_bot"
BOT_FILE="spam_filter_bot.py"
SERVICE_NAME="spam_filter_bot"
LOG_FILE="/var/log/autodeploy.log"
HASH_FILE="$BOT_DIR/.last_deploy_hash"
BRANCH_FILE="$BOT_DIR/.deploy_branch"

# Дефолтная ветка
DEFAULT_BRANCH="claude/telegram-spam-filter-bots-7akBl"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"
}

# Создаем директорию если нет
mkdir -p "$BOT_DIR"

# Читаем ветку из файла или используем дефолтную
if [ -f "$BRANCH_FILE" ]; then
    BRANCH=$(cat "$BRANCH_FILE" | tr -d '\n')
else
    BRANCH="$DEFAULT_BRANCH"
    echo "$BRANCH" > "$BRANCH_FILE"
fi

REPO_URL="https://raw.githubusercontent.com/soloveyska1/BMR/$BRANCH"

# Сначала проверяем, не обновилась ли ветка в репозитории
REMOTE_BRANCH_URL="https://raw.githubusercontent.com/soloveyska1/BMR/$BRANCH/.deploy_branch"
NEW_BRANCH=$(curl -sL "$REMOTE_BRANCH_URL?$(date +%s)" 2>/dev/null | tr -d '\n')

if [ -n "$NEW_BRANCH" ] && [ "$NEW_BRANCH" != "$BRANCH" ]; then
    log "Ветка изменилась: $BRANCH -> $NEW_BRANCH"
    BRANCH="$NEW_BRANCH"
    echo "$BRANCH" > "$BRANCH_FILE"
    REPO_URL="https://raw.githubusercontent.com/soloveyska1/BMR/$BRANCH"
    # Сбрасываем хеш чтобы форсировать обновление
    rm -f "$HASH_FILE"
fi

# Получаем текущий хеш файла на GitHub (с cache-busting)
REMOTE_HASH=$(curl -sL "$REPO_URL/$BOT_FILE?$(date +%s)" | md5sum | cut -d' ' -f1)

if [ -z "$REMOTE_HASH" ] || [ "$REMOTE_HASH" = "d41d8cd98f00b204e9800998ecf8427e" ]; then
    log "ERROR: Не удалось получить файл с GitHub (ветка: $BRANCH)"
    exit 1
fi

# Получаем сохраненный хеш последнего деплоя
if [ -f "$HASH_FILE" ]; then
    LOCAL_HASH=$(cat "$HASH_FILE")
else
    LOCAL_HASH=""
fi

# Сравниваем хеши
if [ "$REMOTE_HASH" != "$LOCAL_HASH" ]; then
    log "Обнаружено обновление! Ветка: $BRANCH. Деплою..."

    # Скачиваем новую версию (с cache-busting)
    curl -sL -o "$BOT_DIR/$BOT_FILE.new" "$REPO_URL/$BOT_FILE?$(date +%s)"

    if [ $? -eq 0 ] && [ -s "$BOT_DIR/$BOT_FILE.new" ]; then
        # Бэкапим старую версию
        if [ -f "$BOT_DIR/$BOT_FILE" ]; then
            cp "$BOT_DIR/$BOT_FILE" "$BOT_DIR/$BOT_FILE.backup"
        fi

        # Заменяем файл
        mv "$BOT_DIR/$BOT_FILE.new" "$BOT_DIR/$BOT_FILE"

        # Перезапускаем сервис
        systemctl restart "$SERVICE_NAME"

        if [ $? -eq 0 ]; then
            # Сохраняем новый хеш
            echo "$REMOTE_HASH" > "$HASH_FILE"
            log "SUCCESS: Деплой завершен (ветка: $BRANCH), сервис перезапущен"
        else
            log "ERROR: Не удалось перезапустить сервис"
            # Откатываемся
            if [ -f "$BOT_DIR/$BOT_FILE.backup" ]; then
                mv "$BOT_DIR/$BOT_FILE.backup" "$BOT_DIR/$BOT_FILE"
                systemctl restart "$SERVICE_NAME"
                log "ROLLBACK: Откат к предыдущей версии"
            fi
        fi
    else
        log "ERROR: Не удалось скачать файл"
        rm -f "$BOT_DIR/$BOT_FILE.new"
    fi
fi
