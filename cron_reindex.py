#!/usr/bin/env python3
"""Reindexación diaria de Notion. Pensado para ejecutarse via cron.

Uso con crontab (ejecutar cada día a las 6:00 AM):
    0 6 * * * cd /ruta/a/adk-python && .venv/bin/python cron_reindex.py

O para probar manualmente:
    python cron_reindex.py
"""
import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

from notion_shared.indexer import NotionIndexer

AGENTS = [
    ("AWS", "NOTION_TOKEN_AWS", ".data/aws_index.json"),
    ("GCP", "NOTION_TOKEN_GCP", ".data/gcp_index.json"),
]


def reindex_all():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    for name, env_var, rel_path in AGENTS:
        token = os.getenv(env_var, "")
        if not token:
            logger.warning(f"{name}: {env_var} no configurado, saltando")
            continue
        index_path = os.path.join(base_dir, rel_path)
        logger.info(f"=== Indexando {name} ===")
        try:
            indexer = NotionIndexer(token, index_path)
            count = indexer.index_all()
            logger.info(f"{name}: {count} documentos indexados")
        except Exception as e:
            logger.error(f"{name}: Error durante indexación: {e}")


if __name__ == "__main__":
    reindex_all()
