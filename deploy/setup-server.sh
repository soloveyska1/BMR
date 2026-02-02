#!/bin/bash
# BMR Server Setup Script
# Одноразовая настройка сервера для автодеплоя

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}========================================${NC}"
echo -e "${YELLOW}  BMR Bots - Server Setup              ${NC}"
echo -e "${YELLOW}========================================${NC}"

# Check if running as root
if [ "$EUID" -eq 0 ]; then
    echo -e "${RED}Please run as regular user (not root)${NC}"
    exit 1
fi

PROJECT_DIR="${1:-$HOME/BMR}"
PYTHON_PATH=$(which python3)

echo -e "${GREEN}Project directory: $PROJECT_DIR${NC}"
echo -e "${GREEN}Python path: $PYTHON_PATH${NC}"

# Clone or update repository
if [ -d "$PROJECT_DIR" ]; then
    echo -e "${YELLOW}Project exists, updating...${NC}"
    cd "$PROJECT_DIR"
    git pull
else
    echo -e "${GREEN}Cloning repository...${NC}"
    git clone https://github.com/soloveyska1/BMR.git "$PROJECT_DIR"
    cd "$PROJECT_DIR"
fi

# Install dependencies
echo -e "${GREEN}Installing Python dependencies...${NC}"
pip install -r requirements.txt

# Create .env files if not exist
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo -e "${YELLOW}Created .env - please edit with your tokens!${NC}"
fi

if [ ! -f "spam_bot.env" ]; then
    cp spam_bot.env.example spam_bot.env
    echo -e "${YELLOW}Created spam_bot.env - please edit with your tokens!${NC}"
fi

# Create systemd service files
echo -e "${GREEN}Creating systemd service files...${NC}"

# Message Collector Bot Service
sudo tee /etc/systemd/system/bmr-collector-bot.service > /dev/null << EOF
[Unit]
Description=BMR Message Collector Telegram Bot
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$PROJECT_DIR
ExecStart=$PYTHON_PATH bot.py
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

# Spam Filter Bot Service
sudo tee /etc/systemd/system/bmr-spam-bot.service > /dev/null << EOF
[Unit]
Description=BMR Anti-Spam Telegram Bot
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$PROJECT_DIR
ExecStart=$PYTHON_PATH spam_filter_bot.py
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

# Reload systemd
sudo systemctl daemon-reload

# Enable services
sudo systemctl enable bmr-collector-bot
sudo systemctl enable bmr-spam-bot

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Setup completed!                     ${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo "1. Edit .env with your bot token and channel ID"
echo "2. Edit spam_bot.env with your spam bot token"
echo "3. Start the bots:"
echo "   sudo systemctl start bmr-collector-bot"
echo "   sudo systemctl start bmr-spam-bot"
echo ""
echo "View logs:"
echo "   journalctl -u bmr-collector-bot -f"
echo "   journalctl -u bmr-spam-bot -f"
