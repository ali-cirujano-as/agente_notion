"""HTTP handler de Slack para Cloud Run con FastAPI + slack-bolt.

Reemplaza slack_bot.py (Socket Mode) con un handler HTTP stateless
compatible con Cloud Run. Usa SlackRequestHandler de slack-bolt para
integrar con FastAPI.

Requisitos: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 3.3, 4.2, 4.3, 4.4, 4.5, 7.5
"""

import asyncio
import logging
import os
import re
import threading
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from slack_bolt import App
from slack_bolt.adapter.fastapi import SlackRequestHandler

from google.adk.runners import Runner
from google.genai import types

from storage.gcs_client import GCSClient
from storage.whitelist import CloudWhitelist
from notion_shared.indexer import NotionIndexer

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

    # Caché de emails de usuarios para no llamar a Slack API en cada mensaje
    _user_email_cache: dict[str, str] = {}

    def _get_user_email(client, user_id: str) -> str:
        """Obtiene el email del usuario desde Slack API (con caché)."""
        if user_id in _user_email_cache:
            return _user_email_cache[user_id]
        try:
            info = client.users_info(user=user_id)
            email = info["user"]["profile"].get("email", "")
            name = info["user"]["real_name"]
            _user_email_cache[user_id] = email
            logger.info(f"Usuario identificado: {user_id} → {name} ({email})")
            return email
        except Exception as e:
            logger.warning(f"No pude obtener email de {user_id}: {e}")
            return ""

    # --- Handler: mensajes directos ---
    @slack_app.event("message")
    def handle_message(event, client, ack, body):
        ack()
        logger.info(f"Evento recibido: channel_type={event.get('channel_type')}, user={event.get('user')}, text={event.get('text', '')[:50]}")
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

        # Obtener email del usuario para contexto personalizado
        user_email = _get_user_email(client, user_id)
        
        # Añadir contexto del usuario a la consulta
        if user_email:
            context_prefix = f"[CONTEXTO: El usuario que pregunta es {user_email}. Si dice 'mis provisiones', 'mis clientes', 'lo mío', etc., filtra por su email en las columnas 'Comercial Responsable Altostratus' o 'Assignee'.]\n\n"
            enriched_text = context_prefix + clean_text
        else:
            enriched_text = clean_text

        # Enviar indicador de que está trabajando
        client.chat_postMessage(channel=channel, text="🔍 Consultando la documentación...")

        # Procesar consulta ADK en background
        def _process_query():
            try:
                response = _call_agent_async(runner, user_id, enriched_text, session_service)
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

    @api.post("/reindex")
    async def reindex(req: Request):
        """Endpoint de reindexación invocado por Cloud Scheduler.

        Verifica autenticación por header, ejecuta indexación completa
        de Notion y sube el resultado a Cloud Storage.

        Requisitos: 4.2, 4.3, 4.4, 4.5
        """
        # Verificar autenticación
        expected_token = os.getenv("REINDEX_AUTH_TOKEN", "")
        auth_header = req.headers.get("authorization", "")

        if not expected_token or auth_header != f"Bearer {expected_token}":
            return JSONResponse(status_code=403, content={"error": "Forbidden"})

        # Determinar configuración según BOT_TYPE
        bot_type = os.getenv("BOT_TYPE", "").lower()
        if bot_type == "aws":
            notion_token = os.getenv("NOTION_TOKEN_AWS", "") or os.getenv("NOTION_TOKEN", "")
            cloud_filter = ["aws"]
            gcs_index_path = "aws/index.json"
            local_index_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), ".data/aws_index.json"
            )
        elif bot_type == "gcp":
            notion_token = os.getenv("NOTION_TOKEN_GCP", "") or os.getenv("NOTION_TOKEN", "")
            cloud_filter = ["gcp", "gws"]
            gcs_index_path = "gcp/index.json"
            local_index_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), ".data/gcp_index.json"
            )
        else:
            logger.error(f"BOT_TYPE no válido para reindexación: '{bot_type}'")
            return JSONResponse(status_code=500, content={"error": "BOT_TYPE not configured"})

        if not notion_token:
            logger.error("NOTION_TOKEN no configurado para reindexación")
            return JSONResponse(status_code=500, content={"error": "NOTION_TOKEN not configured"})

        # Ejecutar indexación
        try:
            indexer = NotionIndexer(notion_token, local_index_path, cloud_filter=cloud_filter)
            count = indexer.index_all()

            # Subir índice a Cloud Storage
            indexer.save_index_to_gcs(gcs_client, gcs_index_path)

            logger.info(f"Reindexación completada: {count} documentos indexados")
            return JSONResponse(status_code=200, content={"status": "ok", "documents_indexed": count})
        except Exception as e:
            logger.error(f"Error durante reindexación: {e}")
            return JSONResponse(status_code=500, content={"error": str(e)})

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


# --- Resumen diario automático ---

def start_daily_summary_timer(slack_app: App, whitelist: CloudWhitelist, gcs_client: GCSClient, bot_name: str):
    """Inicia un timer que envía resúmenes los lunes a las 9:00 AM hora España."""
    import time
    from datetime import datetime, timedelta
    import pytz

    SPAIN_TZ = pytz.timezone("Europe/Madrid")
    TARGET_HOUR = 9
    TARGET_WEEKDAY = 0  # Lunes = 0

    # URLs de las vistas para el resumen
    bot_type = os.getenv("BOT_TYPE", "").lower()
    if bot_type == "aws":
        URL_PROVISIONES = "https://www.notion.so/altostratus-es/AWS-Listado-Provisiones-Bloqueadas-1aebbebfb49b8098b107e12b0c92a5de"
        URL_RENOVACIONES = "https://www.notion.so/altostratus-es/Listado-de-provisiones-en-curso-EPPM-2a1bbebfb49b80448253f24cf172d70c"
    else:
        URL_PROVISIONES = "https://www.notion.so/altostratus-es/GCP-Listado-Provisiones-Bloqueadas-1acbbebfb49b800c9b8af8d967f12429"
        URL_RENOVACIONES = "https://www.notion.so/altostratus-es/GWS-Avisos-de-Renovaci-n-1acbbebfb49b80ff86eec0bc50f253fe"

    def _get_user_email_for_summary(client, user_id: str) -> str:
        try:
            info = client.users_info(user=user_id)
            return info["user"]["profile"].get("email", "")
        except Exception:
            return ""

    def _count_user_data(email: str, index_docs: list) -> dict:
        """Cuenta provisiones bloqueadas y renovaciones del usuario."""
        email_lower = email.lower()
        n_provisiones = 0
        n_renovaciones = 0

        for doc in index_docs:
            content = doc.get("content", "")
            lines = content.split("\n")
            for line in lines:
                if " | " not in line or "Cliente:" not in line:
                    continue
                line_lower = line.lower()
                if email_lower in line_lower:
                    if "bloqueado" in line_lower or "bloqueo" in line_lower:
                        n_provisiones += 1
                    elif "renovación" in line_lower or "renewal" in line_lower:
                        n_renovaciones += 1

        return {"provisiones": n_provisiones, "renovaciones": n_renovaciones}

    def _send_weekly_summaries():
        """Envía resúmenes a todos los usuarios de la whitelist."""
        from slack_sdk import WebClient

        bot_token = os.getenv("SLACK_BOT_TOKEN", "")
        if not bot_token:
            logger.warning("No se puede enviar resumen: SLACK_BOT_TOKEN no configurado")
            return

        client = WebClient(token=bot_token)

        prefix = bot_name.lower().replace(" ", "_").split("_")[0]
        index_data = gcs_client.read_json(f"{prefix}/index.json")
        if not index_data:
            logger.warning("No se puede enviar resumen: índice vacío")
            return
        index_docs = index_data.get("documents", [])

        users = whitelist.list_users()
        logger.info(f"Enviando resumen semanal a {len(users)} usuarios...")

        for user_id in users:
            try:
                email = _get_user_email_for_summary(client, user_id)
                if not email:
                    continue

                data = _count_user_data(email, index_docs)
                n_prov = data["provisiones"]
                n_renov = data["renovaciones"]

                if not n_prov and not n_renov:
                    continue

                # Formato corto con links
                parts = []
                if n_prov:
                    parts.append(f"{n_prov} provisiones bloqueadas")
                if n_renov:
                    parts.append(f"{n_renov} renovaciones próximas")

                msg = f"☀️ Buenos días! Tienes {' y '.join(parts)}. ¿Quieres que las revisemos?\n\n"
                msg += f"📎 <{URL_PROVISIONES}|Ver provisiones> | <{URL_RENOVACIONES}|Ver renovaciones>"

                dm = client.conversations_open(users=[user_id])
                client.chat_postMessage(channel=dm["channel"]["id"], text=msg)
                logger.info(f"Resumen enviado a {user_id} ({email})")

            except Exception as e:
                logger.warning(f"Error enviando resumen a {user_id}: {e}")

    def _timer_loop():
        """Loop que espera hasta el próximo lunes a las 9:00 AM España."""
        while True:
            now = datetime.now(SPAIN_TZ)
            # Calcular próximo lunes a las 9:00
            days_until_monday = (TARGET_WEEKDAY - now.weekday()) % 7
            if days_until_monday == 0 and now.hour >= TARGET_HOUR:
                days_until_monday = 7  # Ya pasó este lunes, esperar al siguiente

            target = (now + timedelta(days=days_until_monday)).replace(
                hour=TARGET_HOUR, minute=0, second=0, microsecond=0
            )

            wait_seconds = (target - now).total_seconds()
            logger.info(f"Resumen semanal programado para {target.strftime('%A %d/%m a las %H:%M')} ({wait_seconds/3600:.1f}h)")
            time.sleep(wait_seconds)

            try:
                _send_weekly_summaries()
            except Exception as e:
                logger.error(f"Error en resumen semanal: {e}")

    thread = threading.Thread(target=_timer_loop, daemon=True)
    thread.start()
    logger.info("Timer de resumen semanal iniciado (lunes 9:00 AM España)")


# --- Alerta de renovaciones a 30 días ---

def start_renewal_alert_timer(whitelist: CloudWhitelist, gcs_client: GCSClient, bot_name: str):
    """Envía alertas diarias cuando una renovación vence en 30 días o menos."""
    import time
    from datetime import datetime, timedelta, date
    import pytz

    SPAIN_TZ = pytz.timezone("Europe/Madrid")
    TARGET_HOUR = 9
    ALERT_DAYS = 30  # Alertar cuando faltan 30 días o menos

    bot_type = os.getenv("BOT_TYPE", "").lower()
    if bot_type == "aws":
        URL_RENOVACIONES = "https://www.notion.so/altostratus-es/Listado-de-provisiones-en-curso-EPPM-2a1bbebfb49b80448253f24cf172d70c"
    else:
        URL_RENOVACIONES = "https://www.notion.so/altostratus-es/GWS-Avisos-de-Renovaci-n-1acbbebfb49b80ff86eec0bc50f253fe"

    def _check_and_alert():
        """Verifica renovaciones próximas y envía alertas."""
        from slack_sdk import WebClient

        bot_token = os.getenv("SLACK_BOT_TOKEN", "")
        if not bot_token:
            return

        client = WebClient(token=bot_token)
        prefix = bot_name.lower().replace(" ", "_").split("_")[0]
        index_data = gcs_client.read_json(f"{prefix}/index.json")
        if not index_data:
            return
        index_docs = index_data.get("documents", [])

        today = date.today()
        alert_threshold = today + timedelta(days=ALERT_DAYS)

        # Buscar renovaciones que vencen en 30 días o menos
        alerts_by_email = {}  # email → lista de (cliente, fecha)

        for doc in index_docs:
            for line in doc.get("content", "").split("\n"):
                if " | " not in line or "Fecha Fin Real:" not in line:
                    continue

                parts = line.split(" | ")
                cliente = ""
                fecha_str = ""
                email = ""

                for part in parts:
                    if part.startswith("Cliente: "):
                        cliente = part.replace("Cliente: ", "")
                    elif part.startswith("Fecha Fin Real: "):
                        fecha_str = part.replace("Fecha Fin Real: ", "").strip()
                    elif part.startswith("Comercial Responsable Altostratus: "):
                        email = part.replace("Comercial Responsable Altostratus: ", "").strip()

                if not fecha_str or not email or not cliente:
                    continue

                try:
                    fecha = date.fromisoformat(fecha_str[:10])
                except (ValueError, IndexError):
                    continue

                # Alertar si vence en exactamente 30 días (±1 día)
                days_left = (fecha - today).days
                if 29 <= days_left <= 31:
                    if email not in alerts_by_email:
                        alerts_by_email[email] = []
                    alerts_by_email[email].append((cliente, fecha_str))

        if not alerts_by_email:
            logger.info("No hay renovaciones a 30 días hoy")
            return

        # Enviar alertas a los comerciales
        users = whitelist.list_users()
        for user_id in users:
            try:
                info = client.users_info(user=user_id)
                user_email = info["user"]["profile"].get("email", "")
                if not user_email or user_email not in alerts_by_email:
                    continue

                renewals = alerts_by_email[user_email]
                for cliente, fecha in renewals:
                    msg = f"⚠️ La renovación de *{cliente}* vence en 30 días ({fecha}).\n📎 <{URL_RENOVACIONES}|Ver renovaciones>"
                    dm = client.conversations_open(users=[user_id])
                    client.chat_postMessage(channel=dm["channel"]["id"], text=msg)
                    logger.info(f"Alerta de renovación enviada a {user_id}: {cliente}")

            except Exception as e:
                logger.warning(f"Error enviando alerta a {user_id}: {e}")

    def _timer_loop():
        """Check diario a las 9:00 AM España."""
        while True:
            now = datetime.now(SPAIN_TZ)
            target = now.replace(hour=TARGET_HOUR, minute=5, second=0, microsecond=0)
            if now >= target:
                target += timedelta(days=1)

            # Solo ejecutar en días laborables (lunes a viernes)
            while target.weekday() >= 5:  # 5=sábado, 6=domingo
                target += timedelta(days=1)

            wait_seconds = (target - now).total_seconds()
            logger.info(f"Alerta de renovaciones programada en {wait_seconds/3600:.1f}h")
            time.sleep(wait_seconds)

            try:
                _check_and_alert()
            except Exception as e:
                logger.error(f"Error en alerta de renovaciones: {e}")

    thread = threading.Thread(target=_timer_loop, daemon=True)
    thread.start()
    logger.info("Timer de alertas de renovación iniciado (diario 9:05 AM, L-V)")
