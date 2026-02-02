#!/bin/bash
# BMR Bots Deploy Script
# Автоматический деплой при push в репозиторий

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

PROJECT_DIR="${PROJECT_DIR:-$HOME/BMR}"
USE_DOCKER="${USE_DOCKER:-false}"

echo -e "${YELLOW}[$(date '+%Y-%m-%d %H:%M:%S')] Starting BMR deployment...${NC}"

cd "$PROJECT_DIR"

# Pull latest changes
echo -e "${GREEN}Pulling latest changes...${NC}"
git fetch origin
git reset --hard origin/main 2>/dev/null || git reset --hard origin/master

if [ "$USE_DOCKER" = "true" ]; then
    # Docker deployment
    echo -e "${GREEN}Deploying with Docker...${NC}"
    docker-compose down
    docker-compose build --no-cache
    docker-compose up -d
    docker image prune -f
    echo -e "${GREEN}Docker containers started!${NC}"
else
    # Systemd deployment
    echo -e "${GREEN}Installing dependencies...${NC}"
    pip install -r requirements.txt --quiet

    echo -e "${GREEN}Restarting services...${NC}"
    sudo systemctl restart bmr-collector-bot 2>/dev/null || echo -e "${YELLOW}bmr-collector-bot not configured${NC}"
    sudo systemctl restart bmr-spam-bot 2>/dev/null || echo -e "${YELLOW}bmr-spam-bot not configured${NC}"
fi

echo -e "${GREEN}[$(date '+%Y-%m-%d %H:%M:%S')] Deployment completed successfully!${NC}"
