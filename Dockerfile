FROM python:3.12-slim

WORKDIR /app

# Зависимости отдельным слоем для кэширования
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Исходный код
COPY bot/ ./bot/

# Директория для SQLite-базы создаётся в runtime через volume
RUN mkdir -p data

CMD ["python", "-m", "bot.main"]
