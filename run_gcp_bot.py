#!/usr/bin/env python3
"""Arranca el bot de Slack para documentación GCP."""
import os
from dotenv import load_dotenv
from notion_shared.indexer import NotionIndexer
from slack_bot import run_bot

load_dotenv()

indexer = NotionIndexer(
    os.getenv("NOTION_TOKEN_GCP", ""),
    os.path.join(os.path.dirname(__file__), ".data", "gcp_index.json"),
)

allowed = set(filter(None, os.getenv("SLACK_ALLOWED_USERS_GCP", "").split(",")))

run_bot(
    bot_token=os.getenv("SLACK_BOT_TOKEN_GCP", ""),
    app_token=os.getenv("SLACK_APP_TOKEN_GCP", ""),
    allowed_users=allowed,
    indexer=indexer,
    bot_name="GCP Notion Bot",
)
