"""HTTP handler de Slack para Cloud Run con FastAPI + slack-bolt.

Reemplaza slack_bot.py (Socket Mode) con un handler HTTP stateless
compatible con Cloud Run. Usa SlackRequestHandler de slack-bolt para
integrar con FastAPI.

Requisitos: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 3.3, 7.5
"""

import asyncio
import logging
import os
import re
import threading
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from slack_bolt import App
from slack_bolt.adapter.fastapi import SlackRequestHandler

from google.adk.runners import Runner
from google.genai import types

from storage.gcs_client import GCSClient
from storage.whitelist import CloudWhitelist

logger = logging.getLogger(__name__)

ADMIN_USERS = set(filter(None, os.getenv("SLACK_ADMIN_USERS", "").split(",")))

# Sesiones por usuario para mantener contexto de conversación
_user_sessions: dict[str, str] = {}


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


def _log_query(gcs_client: GCSClient, bot_name: str, user_id: str, query: str, response_preview: str):
    """Registra una consulta en el query log de Cloud Storage."""
    prefix = bot_name.lower().replace(" ", "_").split("_")[0]  # "aws" o "gcp"
    path = f"{prefix}/query_log.jsonl"
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "bot": bot_name,
        "user_id": user_id,
        "query": query,
        "response_preview": response_preview,
    }
    try:
        gcs_client.append_jsonl(path, entry)
    except Exception as e:
        logger.error(f"Error al registrar query log: {e}")


def _call_agent_async(runner: Runner, user_id: str, text: str, session_service) -> str:
    """Ejecuta el agente ADK y devuelve la respuesta como texto."""

    async def _run():
        # Reutilizar sesión existente del usuario o crear una nueva
        session_id = _user_sessions.get(user_id)
        session = None
        if session_id:
            try:
                session = await session_service.get_session(
                    app_name=runner.app_name, user_id=user_id, session_id=session_id
                )
            except Exception:
                session = None

        if not session:
            session = await session_service.create_session(
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
            if event.is_final_response() and event.content and event.content.parts:
                for part in event.content.parts:
                    if part.text:
                        response_text += part.text
        return response_text

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(_run())
    finally:
        loop.close()


def _handle_admin(text: str, user_id: str, whitelist: CloudWhitelist, client, channel: str):
    """Procesa comandos admin. Devuelve True si era un comando admin."""
    text_lower = text.lower().strip()
    if not text_lower.startswith("admin"):
        return False

    if user_id not in ADMIN_USERS:
        client.chat_postMessage(channel=channel, text="⛔ No tienes permisos de administrador.")
        return True

    parts = text_lower.split()
    if len(parts) < 2:
        client.chat_postMessage(
            channel=channel,
            text="Comandos: `admin lista`, `admin añadir @usuario`, `admin quitar @usuario`",
        )
        return True

    cmd = parts[1]

    if cmd == "lista":
        users = whitelist.list_users()
        if not users:
            client.chat_postMessage(channel=channel, text="📋 La lista blanca está vacía.")
        else:
            user_list = "\n".join(f"• <@{u}>" for u in sorted(users))
            client.chat_postMessage(channel=channel, text=f"📋 Usuarios con acceso:\n{user_list}")
        return True

    if cmd in ("añadir", "add"):
        mentioned = re.findall(r"<@([A-Z0-9]+)>", text)
        if not mentioned:
            client.chat_postMessage(channel=channel, text="Usa: `admin añadir @usuario`")
            return True
        for uid in mentioned:
            whitelist.add(uid)
        names = ", ".join(f"<@{u}>" for u in mentioned)
        client.chat_postMessage(channel=channel, text=f"✅ Añadido(s): {names}")
        return True

    if cmd in ("quitar", "remove"):
        mentioned = re.findall(r"<@([A-Z0-9]+)>", text)
        if not mentioned:
            client.chat_postMessage(channel=channel, text="Usa: `admin quitar @usuario`")
            return True
        for uid in mentioned:
            whitelist.remove(uid)
        names = ", ".join(f"<@{u}>" for u in mentioned)
        client.chat_postMessage(channel=channel, text=f"🗑️ Eliminado(s): {names}")
        return True

    client.chat_postMessage(
        channel=channel,
        text="Comandos: `admin lista`, `admin añadir @usuario`, `admin quitar @usuario`",
    )
    return True


def create_app(
    bot_token: str,
    signing_secret: str,
    adk_agent,
    bot_name: str,
    gcs_client: GCSClient,
    session_service,
) -> FastAPI:
    """Crea la aplicación FastAPI con el handler HTTP de Slack.

    Args:
        bot_token: Token OAuth del bot de Slack.
        signing_secret: Signing secret para verificar requests de Slack.
        adk_agent: Agente ADK configurado para responder consultas.
        bot_name: Nombre del bot (e.g. "AWS Info Bot").
        gcs_client: Cliente de Cloud Storage para persistencia.
        session_service: Servicio de sesiones ADK (DatabaseSessionService o InMemorySessionService).

    Returns:
        Aplicación FastAPI lista para servir con uvicorn.
    """
    # Determinar prefijo para Cloud Storage (aws o gcp)
    prefix = bot_name.lower().replace(" ", "_").split("_")[0]

    # Inicializar slack-bolt con signing secret para verificación HTTP
    slack_app = App(token=bot_token, signing_secret=signing_secret)

    # Inicializar whitelist desde Cloud Storage
    whitelist = CloudWhitelist(gcs_client, prefix)

    # Inicializar runner ADK
    runner = Runner(
        agent=adk_agent,
        app_name=bot_name,
        session_service=session_service,
    )

    # --- Handler: solicitar acceso ---
    @slack_app.action("request_access")
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
        # Notificar a admins
        _notify_admins_access_request(client, user_id, bot_name)

    # --- Handler: aprobar acceso ---
    @slack_app.action("approve_access")
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

    # --- Handler: rechazar acceso ---
    @slack_app.action("reject_access")
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

    # --- Handler: mensajes directos ---
    @slack_app.event("message")
    def handle_message(body, client):
        event = body.get("event", {})
        # Solo procesar DMs, ignorar mensajes de bots
        if event.get("channel_type") != "im" or event.get("bot_id"):
            return

        user_id = event.get("user", "")
        text = event.get("text", "")
        channel = event.get("channel", "")

        # Procesar comandos admin primero
        if _handle_admin(text, user_id, whitelist, client, channel):
            return

        # Limpiar menciones
        clean_text = _clean_mention(text)
        if not clean_text.strip():
            return

        # Verificar autorización
        if user_id not in ADMIN_USERS and not whitelist.is_allowed(user_id):
            _send_access_request_prompt(client, channel)
            return

        # Procesar consulta ADK en background (ack ya fue enviado por slack-bolt)
        def _process_query():
            try:
                response = _call_agent_async(runner, user_id, clean_text, session_service)
                if response.strip():
                    client.chat_postMessage(
                        channel=channel,
                        text=_markdown_to_slack(response),
                    )
                else:
                    client.chat_postMessage(
                        channel=channel,
                        text="No pude generar una respuesta. Intenta reformular la pregunta.",
                    )
                # Registrar consulta en Cloud Storage
                _log_query(
                    gcs_client, bot_name, user_id, clean_text,
                    response[:200] if response else "(sin respuesta)",
                )
            except Exception as e:
                logger.error(f"Error al procesar consulta: {e}")
                client.chat_postMessage(
                    channel=channel,
                    text="❌ Hubo un error al procesar tu pregunta. Inténtalo de nuevo.",
                )
                _log_query(gcs_client, bot_name, user_id, clean_text, f"ERROR: {e}")

        thread = threading.Thread(target=_process_query, daemon=True)
        thread.start()

    # --- Crear aplicación FastAPI ---
    api = FastAPI(title=bot_name)
    handler = SlackRequestHandler(slack_app)

    @api.post("/slack/events")
    async def slack_events(req: Request):
        return await handler.handle(req)

    @api.get("/health")
    async def health():
        return {"status": "ok"}

    return api


def _send_access_request_prompt(client, channel: str):
    """Envía mensaje con botón para solicitar acceso."""
    client.chat_postMessage(
        channel=channel,
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
