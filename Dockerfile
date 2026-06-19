# Always-on engine + dashboard image.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    ALLOW_NETWORK=true \
    TERMINAL_DB_PATH=/app/data/terminal.db

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p /app/data /app/logs

# Default process: the always-on scanner/alert engine.
# (The dashboard is run as a separate service — see docker-compose.yml.)
CMD ["python", "-m", "src.engine.scheduler"]
