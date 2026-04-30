"""Entrypoint para Cloud Run: selecciona agente por BOT_TYPE y arranca FastAPI.

Lee variables de entorno para configurar el servicio:
- BOT_TYPE: "aws" o "gcp" (determina qué agente cargar)
- GCS_BUCKET: nombre del bucket de Cloud Storage
- DATABASE_URL: URL de conexión a Cloud SQL PostgreSQL (postgresql+asyncpg://...)
- SLACK_BOT_TOKEN: token OAuth del bot de Slack
- SLACK_SIGNING_SECRET: signing secret para verificar requests de Slack

Requisitos: 2.5, 2.6
"""

import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# --- Variables de entorno ---
BOT_TYPE = os.getenv("BOT_TYPE", "").lower()
GCS_BUCKET = os.getenv("GCS_BUCKET", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "")
SLACK_SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET", "")

# --- Validar configuración mínima ---
if not BOT_TYPE:
    logger.error("BOT_TYPE no configurado. Debe ser 'aws' o 'gcp'.")
    sys.exit(1)

if BOT_TYPE not in ("aws", "gcp"):
    logger.error(f"BOT_TYPE inválido: '{BOT_TYPE}'. Debe ser 'aws' o 'gcp'.")
    sys.exit(1)

if not SLACK_BOT_TOKEN:
    logger.error("SLACK_BOT_TOKEN no configurado.")
    sys.exit(1)

if not SLACK_SIGNING_SECRET:
    logger.error("SLACK_SIGNING_SECRET no configurado.")
    sys.exit(1)

if not GCS_BUCKET:
    logger.error("GCS_BUCKET no configurado.")
    sys.exit(1)

# --- Instanciar servicio de sesiones ---
# Si DATABASE_URL está configurado, usar DatabaseSessionService (Cloud SQL PostgreSQL)
# Si no, usar InMemorySessionService para desarrollo local
if DATABASE_URL:
    from google.adk.sessions import DatabaseSessionService

    session_service = DatabaseSessionService(db_url=DATABASE_URL)
    logger.info("Usando DatabaseSessionService con Cloud SQL PostgreSQL")
else:
    from google.adk.sessions import InMemorySessionService

    session_service = InMemorySessionService()
    logger.warning(
        "DATABASE_URL no configurado. Usando InMemorySessionService "
        "(las sesiones no persistirán entre reinicios)."
    )

# --- Instanciar cliente de Cloud Storage ---
from storage.gcs_client import GCSClient

gcs_client = GCSClient(GCS_BUCKET)
logger.info(f"GCSClient inicializado con bucket: {GCS_BUCKET}")

# --- Importar agente correspondiente ---
if BOT_TYPE == "aws":
    from agents.aws_agent.agent import agent as adk_agent

    bot_name = "AWS Info Bot"
    logger.info("Cargando agente AWS")
elif BOT_TYPE == "gcp":
    from agents.gcp_agent.agent import agent as adk_agent

    bot_name = "GCP Info Bot"
    logger.info("Cargando agente GCP")

# --- Crear aplicación FastAPI ---
from slack_http_bot import create_app, start_daily_summary_timer, start_renewal_alert_timer

app = create_app(
    bot_token=SLACK_BOT_TOKEN,
    signing_secret=SLACK_SIGNING_SECRET,
    adk_agent=adk_agent,
    bot_name=bot_name,
    gcs_client=gcs_client,
    session_service=session_service,
)

# Iniciar timer de resumen diario
prefix = bot_name.lower().replace(" ", "_").split("_")[0]
from storage.whitelist import CloudWhitelist
whitelist_for_summary = CloudWhitelist(gcs_client, prefix)
start_daily_summary_timer(None, whitelist_for_summary, gcs_client, bot_name)
start_renewal_alert_timer(whitelist_for_summary, gcs_client, bot_name)

logger.info(f"Aplicación {bot_name} lista (BOT_TYPE={BOT_TYPE})")

# --- Timer de reindexación a las 6:00 y 15:00 hora España ---
import threading
from notion_shared.indexer import NotionIndexer
import pytz

REINDEX_HOURS = [6, 15]  # 6:00 AM y 15:00 PM hora España
SPAIN_TZ = pytz.timezone("Europe/Madrid")


def _background_reindex():
    """Reindexa a las 6:00 y 15:00 hora España."""
    import time
    from datetime import datetime, timedelta

    notion_token = os.getenv("NOTION_TOKEN_AWS" if BOT_TYPE == "aws" else "NOTION_TOKEN_GCP", "")
    cloud_filter = ["aws"] if BOT_TYPE == "aws" else ["gcp", "gws"]
    gcs_path = f"{BOT_TYPE}/index.json"
    local_path = f".data/{BOT_TYPE}_index.json"

    # Reindexar al arrancar
    try:
        indexer = NotionIndexer(notion_token, local_path, cloud_filter=cloud_filter)
        count = indexer.index_all()
        indexer.save_index_to_gcs(gcs_client, gcs_path)
        logger.info(f"Reindexación inicial completada: {count} documentos")
    except Exception as e:
        logger.error(f"Error en reindexación inicial: {e}")

    # Reindexar a las horas programadas
    while True:
        now = datetime.now(SPAIN_TZ)
        # Encontrar la próxima hora de reindexación
        next_run = None
        for hour in sorted(REINDEX_HOURS):
            target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
            if target > now:
                next_run = target
                break
        if next_run is None:
            # Todas las horas de hoy ya pasaron, programar la primera de mañana
            next_run = (now + timedelta(days=1)).replace(
                hour=REINDEX_HOURS[0], minute=0, second=0, microsecond=0
            )

        wait_seconds = (next_run - now).total_seconds()
        logger.info(f"Próxima reindexación a las {next_run.strftime('%H:%M')} ({wait_seconds/3600:.1f}h)")
        time.sleep(wait_seconds)

        try:
            indexer = NotionIndexer(notion_token, local_path, cloud_filter=cloud_filter)
            count = indexer.index_all()
            indexer.save_index_to_gcs(gcs_client, gcs_path)
            logger.info(f"Reindexación programada completada: {count} documentos")
        except Exception as e:
            logger.error(f"Error en reindexación programada: {e}")


reindex_thread = threading.Thread(target=_background_reindex, daemon=True)
reindex_thread.start()
