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
from slack_http_bot import create_app

app = create_app(
    bot_token=SLACK_BOT_TOKEN,
    signing_secret=SLACK_SIGNING_SECRET,
    adk_agent=adk_agent,
    bot_name=bot_name,
    gcs_client=gcs_client,
    session_service=session_service,
)

logger.info(f"Aplicación {bot_name} lista (BOT_TYPE={BOT_TYPE})")
