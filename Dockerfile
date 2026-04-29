FROM python:3.12-slim

WORKDIR /app

# Instalar dependencias del sistema (sin cron)
RUN apt-get update && apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Dependencias Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar código necesario
COPY notion_shared/ notion_shared/
COPY agents/ agents/
COPY storage/ storage/
COPY slack_http_bot.py .
COPY main.py .

# Crear directorio de datos para desarrollo local
RUN mkdir -p .data

# Puerto de Cloud Run
EXPOSE 8080

# Arrancar con uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
