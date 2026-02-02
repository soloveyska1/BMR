#!/bin/bash
# Автодеплой spam_filter_bot.py
# Проверяет обновления каждую минуту и автоматически деплоит

REPO_URL="https://raw.githubusercontent.com/soloveyska1/BMR/claude/telegram-spam-filter-bots-7akBl"
BOT_FILE="spam_filter_bot.py"
BOT_DIR="/root/spam_bot"
SERVICE_NAME="spam_filter_bot"
LOG_FILE="/var/log/autodeploy.log"
HASH_FILE="/root/spam_bot/.last_deploy_hash"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"
}

# Создаем директорию если нет
mkdir -p "$BOT_DIR"

# Получаем текущий хеш файла на GitHub (с cache-busting)
REMOTE_HASH=$(curl -sL "$REPO_URL/$BOT_FILE?$(date +%s)" | md5sum | cut -d' ' -f1)

if [ -z "$REMOTE_HASH" ]; then
    log "ERROR: Не удалось получить файл с GitHub"
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
    log "Обнаружено обновление! Деплою..."

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
            log "SUCCESS: Деплой завершен, сервис перезапущен"
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
