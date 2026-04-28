#!/usr/bin/env python3
"""Arranca el bot de Slack para documentación GCP."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
from agents.gcp_agent.agent import agent
from slack_bot import run_bot

load_dotenv()

run_bot(
    bot_token=os.getenv("SLACK_BOT_TOKEN_GCP", ""),
    app_token=os.getenv("SLACK_APP_TOKEN_GCP", ""),
    whitelist_path=os.path.join(os.path.dirname(__file__), ".data", "whitelist_gcp.json"),
    adk_agent=agent,
    bot_name="GCP Info Bot",
)
