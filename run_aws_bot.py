#!/usr/bin/env python3
"""Arranca el bot de Slack para documentación AWS."""
import os
from dotenv import load_dotenv
from notion_shared.indexer import NotionIndexer
from slack_bot import run_bot

load_dotenv()

indexer = NotionIndexer(
    os.getenv("NOTION_TOKEN_AWS", ""),
    os.path.join(os.path.dirname(__file__), ".data", "aws_index.json"),
)

run_bot(
    bot_token=os.getenv("SLACK_BOT_TOKEN_AWS", ""),
    app_token=os.getenv("SLACK_APP_TOKEN_AWS", ""),
    whitelist_path=os.path.join(os.path.dirname(__file__), ".data", "whitelist_aws.json"),
    indexer=indexer,
    bot_name="AWS Info Bot",
)
