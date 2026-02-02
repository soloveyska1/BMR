# Multi-stage Dockerfile for BMR Bots
FROM python:3.11-slim as base

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies (for OCR if needed)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-rus \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY *.py ./

# Create volume for database persistence
VOLUME ["/app/data"]

# ===== Message Collector Bot =====
FROM base as collector-bot
CMD ["python", "bot.py"]

# ===== Spam Filter Bot =====
FROM base as spam-bot
CMD ["python", "spam_filter_bot.py"]
