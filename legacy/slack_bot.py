#!/usr/bin/env python3
"""Módulo compartido para bots de Slack conectados a Notion via ADK."""
import asyncio
import json
import os
import logging
import re

from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from notion_shared.indexer import NotionIndexer

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

ADMIN_USERS = set(filter(None, os.getenv("SLACK_ADMIN_USERS", "").split(",")))

# Sesiones por usuario para mantener contexto de conversación
_user_sessions: dict = {}

# Directorio de logs
_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".data")


def _log_query(bot_name: str, user_id: str, query: str, response_preview: str):
    """Guarda un log de cada consulta en .data/query_log.jsonl"""
    from datetime import datetime
    os.makedirs(_LOG_DIR, exist_ok=True)
    log_path = os.path.join(_LOG_DIR, "query_log.jsonl")
    entry = {
        "timestamp": datetime.now().isoformat(),
        "bot": bot_name,
        "user_id": user_id,
        "query": query,
        "response_preview": response_preview,
    }
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

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


def _markdown_to_slack(text: str) -> str:
    """Convierte Markdown a formato Slack."""
    # **negrita** → *negrita*
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)
    # __negrita__ → *negrita*
    text = re.sub(r"__(.+?)__", r"*\1*", text)
    # _cursiva_ → _cursiva_ (ya es igual en Slack)
    # `código` → `código` (ya es igual en Slack)
    # ### heading → *heading*
    text = re.sub(r"^#{1,3}\s+(.+)$", r"*\1*", text, flags=re.MULTILINE)
    return text


def _send_access_request_prompt(say):
    """Envía mensaje con botón para solicitar acceso."""
    say(
        text="No tienes acceso a este bot.",
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "⛔ No tienes acceso a este bot. ¿Quieres solicitar acceso?",
                },
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "🔑 Solicitar acceso"},
                        "style": "primary",
                        "action_id": "request_access",
                    }
                ],
            },
        ],
    )


def _notify_admins_access_request(client, requester_id: str, bot_name: str):
    """Envía DM a cada admin con botones para aprobar/rechazar."""
    for admin_id in ADMIN_USERS:
        try:
            dm = client.conversations_open(users=[admin_id])
            channel = dm["channel"]["id"]
            client.chat_postMessage(
                channel=channel,
                text=f"Solicitud de acceso de <@{requester_id}>",
                blocks=[
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"📩 <@{requester_id}> quiere acceso a *{bot_name}*",
                        },
                    },
                    {
                        "type": "actions",
                        "elements": [
                            {
                                "type": "button",
                                "text": {"type": "plain_text", "text": "✅ Aprobar"},
                                "style": "primary",
                                "action_id": "approve_access",
                                "value": requester_id,
                            },
                            {
                                "type": "button",
                                "text": {"type": "plain_text", "text": "❌ Rechazar"},
                                "style": "danger",
                                "action_id": "reject_access",
                                "value": requester_id,
                            },
                        ],
                    },
                ],
            )
        except Exception as e:
            logger.warning(f"No pude notificar al admin {admin_id}: {e}")


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
            say("📋 La lista blanca está vacía.")
        else:
            user_list = "\n".join(f"• <@{u}>" for u in sorted(whitelist.users))
            say(f"📋 Usuarios con acceso:\n{user_list}")
        return True

    if cmd in ("añadir", "add"):
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


def _call_agent(runner: Runner, user_id: str, text: str) -> str:
    """Ejecuta el agente ADK y devuelve la respuesta como texto."""
    import concurrent.futures

    async def _run():
        # Reutilizar sesión existente del usuario o crear una nueva
        session_id = _user_sessions.get(user_id)
        if session_id:
            try:
                session = await runner.session_service.get_session(
                    app_name=runner.app_name, user_id=user_id, session_id=session_id
                )
            except Exception:
                session = None
        else:
            session = None

        if not session:
            session = await runner.session_service.create_session(
                app_name=runner.app_name, user_id=user_id
            )
            _user_sessions[user_id] = session.id

        content = types.Content(
            role="user", parts=[types.Part.from_text(text=text)]
        )
        response_text = ""
        async for event in runner.run_async(
            user_id=user_id, session_id=session.id, new_message=content
        ):
            author = event.author
            is_final = event.is_final_response()
            logger.info(f"Event: author={author}, final={is_final}")
            if is_final and event.content and event.content.parts:
                for part in event.content.parts:
                    if part.text:
                        response_text += part.text
        logger.info(f"Response text: '{response_text[:200]}'")
        return response_text

    def _thread_run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(_run())
        finally:
            loop.close()

    with concurrent.futures.ThreadPoolExecutor() as pool:
        future = pool.submit(_thread_run)
        return future.result(timeout=120)


def _handle_search(text: str, user_id: str, whitelist: Whitelist, runner: Runner, say):
    """Usa el agente ADK para responder."""
    text = _clean_mention(text)
    if not text.strip():
        return

    if user_id not in ADMIN_USERS and not whitelist.is_allowed(user_id):
        _send_access_request_prompt(say)
        return

    say("🔍 Consultando la documentación...")
    try:
        response = _call_agent(runner, user_id, text)
        if response.strip():
            say(_markdown_to_slack(response))
        else:
            say("No pude generar una respuesta. Intenta reformular la pregunta.")
        # Log de consulta
        _log_query(runner.app_name, user_id, text, response[:200] if response else "(sin respuesta)")
    except Exception as e:
        print(f"!!! ERROR REAL: {type(e).__name__}: {e}", flush=True)
        import traceback
        traceback.print_exc()
        logger.error(f"Error al consultar agente: {e}")
        say("❌ Hubo un error al procesar tu pregunta. Inténtalo de nuevo.")
        _log_query(runner.app_name, user_id, text, f"ERROR: {e}")


def run_bot(bot_token: str, app_token: str, whitelist_path: str, adk_agent: Agent, bot_name: str):
    """Arranca un bot de Slack en Socket Mode."""
    app = App(token=bot_token)
    whitelist = Whitelist(whitelist_path)

    session_service = InMemorySessionService()
    runner = Runner(
        agent=adk_agent,
        app_name=bot_name,
        session_service=session_service,
    )

    # --- Botón: solicitar acceso ---
    @app.action("request_access")
    def handle_request_access(ack, body, client):
        ack()
        user_id = body["user"]["id"]
        # Actualizar el mensaje original
        client.chat_update(
            channel=body["channel"]["id"],
            ts=body["message"]["ts"],
            text="Solicitud enviada.",
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "📨 Solicitud enviada. Un admin la revisará pronto.",
                    },
                }
            ],
        )
        _notify_admins_access_request(client, user_id, bot_name)

    # --- Botón: aprobar acceso ---
    @app.action("approve_access")
    def handle_approve(ack, body, client):
        ack()
        admin_id = body["user"]["id"]
        requester_id = body["actions"][0]["value"]
        if admin_id not in ADMIN_USERS:
            return
        whitelist.add(requester_id)
        # Actualizar mensaje del admin
        client.chat_update(
            channel=body["channel"]["id"],
            ts=body["message"]["ts"],
            text=f"Acceso aprobado para <@{requester_id}>",
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"✅ <@{admin_id}> aprobó el acceso de <@{requester_id}>",
                    },
                }
            ],
        )
        # Notificar al usuario
        try:
            dm = client.conversations_open(users=[requester_id])
            client.chat_postMessage(
                channel=dm["channel"]["id"],
                text=f"🎉 Tu acceso a *{bot_name}* ha sido aprobado. Ya puedes hacer preguntas.",
            )
        except Exception as e:
            logger.warning(f"No pude notificar a {requester_id}: {e}")

    # --- Botón: rechazar acceso ---
    @app.action("reject_access")
    def handle_reject(ack, body, client):
        ack()
        admin_id = body["user"]["id"]
        requester_id = body["actions"][0]["value"]
        if admin_id not in ADMIN_USERS:
            return
        # Actualizar mensaje del admin
        client.chat_update(
            channel=body["channel"]["id"],
            ts=body["message"]["ts"],
            text=f"Acceso rechazado para <@{requester_id}>",
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"❌ <@{admin_id}> rechazó el acceso de <@{requester_id}>",
                    },
                }
            ],
        )
        # Notificar al usuario
        try:
            dm = client.conversations_open(users=[requester_id])
            client.chat_postMessage(
                channel=dm["channel"]["id"],
                text=f"Lo siento, tu solicitud de acceso a *{bot_name}* fue rechazada. Contacta con tu admin si crees que es un error.",
            )
        except Exception as e:
            logger.warning(f"No pude notificar a {requester_id}: {e}")

    # --- Eventos (solo DMs) ---
    @app.event("message")
    def on_dm(body, say):
        event = body.get("event", {})
        if event.get("channel_type") == "im" and not event.get("bot_id"):
            user_id = event.get("user", "")
            text = event.get("text", "")
            if not _handle_admin(text, user_id, whitelist, say):
                _handle_search(text, user_id, whitelist, runner, say)

    logger.info(f"🚀 {bot_name} arrancado. Admins: {ADMIN_USERS}")
    handler = SocketModeHandler(app, app_token)
    handler.start()
