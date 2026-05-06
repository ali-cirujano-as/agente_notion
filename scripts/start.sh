#!/bin/bash
set -e

# Configurar cron para reindexación a las 6:00 y 14:00
echo "0 6,14 * * * cd /app && python cron_reindex.py >> /app/.data/cron.log 2>&1" | crontab -
cron

echo "=== Indexando documentación ==="
python cron_reindex.py

echo "=== Arrancando bots ==="
python run_aws_bot.py &
python run_gcp_bot.py &

# Esperar a que alguno termine (no debería)
wait -n
echo "Un bot se ha detenido, saliendo..."
exit 1
