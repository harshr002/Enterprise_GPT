FROM python:3.12-slim

WORKDIR /app

# System deps kept minimal; pypdf & python-docx are pure-python.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Data dir for the SQLite DB (mount a persistent disk here in production).
RUN mkdir -p /app/data

ENV DATABASE_PATH=/app/data/knowledge.db
EXPOSE 8000

# $PORT is provided by most hosts (Render/Railway). Falls back to 8000.
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
