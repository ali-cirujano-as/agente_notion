#!/usr/bin/env python3
"""Script para indexar contenido de Notion. Ejecutar una vez al día."""
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


def main():
    # Indexar AWS
    aws_token = os.getenv("NOTION_TOKEN_AWS", "")
    if aws_token:
        logger.info("=== Indexando documentación AWS ===")
        aws_indexer = NotionIndexer(
            aws_token,
            os.path.join(os.path.dirname(__file__), ".data", "aws_index.json"),
        )
        aws_count = aws_indexer.index_all()
        logger.info(f"AWS: {aws_count} documentos indexados")
    else:
        logger.warning("NOTION_TOKEN_AWS no configurado")

    # Indexar GCP
    gcp_token = os.getenv("NOTION_TOKEN_GCP", "")
    if gcp_token:
        logger.info("=== Indexando documentación GCP ===")
        gcp_indexer = NotionIndexer(
            gcp_token,
            os.path.join(os.path.dirname(__file__), ".data", "gcp_index.json"),
        )
        gcp_count = gcp_indexer.index_all()
        logger.info(f"GCP: {gcp_count} documentos indexados")
    else:
        logger.warning("NOTION_TOKEN_GCP no configurado")


if __name__ == "__main__":
    main()
