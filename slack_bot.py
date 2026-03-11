#!/usr/bin/env python3
"""Módulo compartido para bots de Slack conectados a Notion via ADK."""
import json
import os
import logging
import re

from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from notion_shared.indexer import NotionIndexer

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

ADMIN_USERS = set(filter(None, os.getenv("SLACK_ADMIN_USERS", "").split(",")))


class Whitelist:
    """Lista blanca de usuarios persistida en JSON."""

    def __init__(self, path: str):
        self.path = path
        self.users: set[str] = set()
        self._load()

    def _load(self):
        if os.path.exists(self.path):
            with open(self.path, "r") as f:
                self.users = set(json.load(f))

    def _save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w") as f:
            json.dump(sorted(self.users), f, indent=2)

    def add(self, user_id: str):
        self.users.add(user_id)
        self._save()

    def remove(self, user_id: str):
        self.users.discard(user_id)
        self._save()

    def is_allowed(self, user_id: str) -> bool:
        return user_id in self.users


def _clean_mention(text: str) -> str:
    """Elimina menciones de bot (<@UXXXXX>) del texto."""
    return re.sub(r"<@[A-Z0-9]+>", "", text).strip()


def _handle_admin(text: str, user_id: str, whitelist: Whitelist, say):
    """Procesa comandos admin. Devuelve True si era un comando admin."""
    text_lower = text.lower().strip()
    if not text_lower.startswith("admin"):
        return False

    if user_id not in ADMIN_USERS:
        say("⛔ No tienes permisos de administrador.")
        return True

    parts = text_lower.split()
    if len(parts) < 2:
        say("Comandos: `admin lista`, `admin añadir @usuario`, `admin quitar @usuario`")
        return True

    cmd = parts[1]

    if cmd == "lista":
        if not whitelist.users:
            say("📋 La lista blanca está vacía (todos tienen acceso).")
        else:
            user_list = "\n".join(f"• <@{u}>" for u in sorted(whitelist.users))
            say(f"📋 Usuarios con acceso:\n{user_list}")
        return True

    if cmd in ("añadir", "add"):
        # Extraer user IDs de menciones <@UXXXXX>
        mentioned = re.findall(r"<@([A-Z0-9]+)>", text)
        if not mentioned:
            say("Usa: `admin añadir @usuario`")
            return True
        for uid in mentioned:
            whitelist.add(uid)
        names = ", ".join(f"<@{u}>" for u in mentioned)
        say(f"✅ Añadido(s): {names}")
        return True

    if cmd in ("quitar", "remove"):
        mentioned = re.findall(r"<@([A-Z0-9]+)>", text)
        if not mentioned:
            say("Usa: `admin quitar @usuario`")
            return True
        for uid in mentioned:
            whitelist.remove(uid)
        names = ", ".join(f"<@{u}>" for u in mentioned)
        say(f"🗑️ Eliminado(s): {names}")
        return True

    say("Comandos: `admin lista`, `admin añadir @usuario`, `admin quitar @usuario`")
    return True


def _handle_search(text: str, user_id: str, whitelist: Whitelist, indexer: NotionIndexer, say):
    """Busca en Notion y responde."""
    text = _clean_mention(text)
    if not text.strip():
        return

    if not whitelist.is_allowed(user_id):
        say("⛔ No tienes acceso a este bot. Contacta con tu admin.")
        return

    text_lower = text.lower()
    if "reindex" in text_lower or "reindexar" in text_lower:
        say("🔄 Reindexando... esto puede tardar un momento.")
        try:
            count = indexer.index_all()
            say(f"✅ Reindexación completada: {count} documentos.")
        except Exception as e:
            say(f"❌ Error al reindexar: {e}")
        return

    say("🔍 Buscando en la documentación...")
    results = indexer.search(text)

    if not results:
        say("No encontré información relevante. Prueba con otros términos o pide reindexar.")
        return

    response = f"📚 Encontré {len(results)} resultado(s):\n\n"
    for i, r in enumerate(results, 1):
        content = r["content"][:500]
        response += f"*{i}. {r['title']}* ({r['type']})\n{content}\n"
        if r.get("url"):
            response += f"🔗 {r['url']}\n"
        response += "\n"
    say(response)


def run_bot(bot_token: str, app_token: str, whitelist_path: str, indexer: NotionIndexer, bot_name: str):
    """Arranca un bot de Slack en Socket Mode."""
    app = App(token=bot_token)
    whitelist = Whitelist(whitelist_path)

    @app.event("app_mention")
    def on_mention(body, say):
        event = body.get("event", {})
        user_id = event.get("user", "")
        text = _clean_mention(event.get("text", ""))
        if not _handle_admin(text, user_id, whitelist, say):
            _handle_search(event.get("text", ""), user_id, whitelist, indexer, say)

    @app.event("message")
    def on_dm(body, say):
        event = body.get("event", {})
        if event.get("channel_type") == "im" and not event.get("bot_id"):
            user_id = event.get("user", "")
            text = event.get("text", "")
            if not _handle_admin(text, user_id, whitelist, say):
                _handle_search(text, user_id, whitelist, indexer, say)

    logger.info(f"🚀 {bot_name} arrancado. Admins: {ADMIN_USERS}")
    handler = SocketModeHandler(app, app_token)
    handler.start()
