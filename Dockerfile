FROM python:3.12-slim

WORKDIR /app

# Instalar cron
RUN apt-get update && apt-get install -y cron && rm -rf /var/lib/apt/lists/*

# Dependencias Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Código
COPY notion_shared/ notion_shared/
COPY agents/ agents/
COPY slack_bot.py .
COPY run_aws_bot.py .
COPY run_gcp_bot.py .
COPY cron_reindex.py .
COPY index_notion.py .
COPY start.sh .

RUN mkdir -p .data
RUN chmod +x start.sh

CMD ["./start.sh"]
