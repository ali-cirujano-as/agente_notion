# Documentación Completa: Agentes BizOps v2 (Cloud Run)

## 1. Visión General

### Qué son

Dos asistentes de IA integrados en Slack que permiten al equipo de BizOps de Altostratus consultar información técnica y operacional sin salir de Slack. Los asistentes leen documentación almacenada en Notion, la procesan y responden preguntas en lenguaje natural usando Gemini 2.5 Flash.

### Los dos bots

| Bot | Nombre en Slack | Qué cubre |
|-----|----------------|-----------|
| AWS Info Bot | aws_info_bot | Provisiones AWS, MPAs, facturación, soporte, cuentas |
| Google Info Bot | google_info_bot | Provisiones GCP/GWS, licencias, renovaciones, facturación, soporte |

### Funcionalidades

- Consultas en lenguaje natural sobre documentación y datos operacionales
- Filtrado automático por cloud (AWS vs GCP/GWS)
- Identificación del usuario por email: si dices "mis provisiones", filtra por ti
- Links a Notion en las respuestas para ir directamente al dato
- Resumen diario a las 9:00 AM con provisiones bloqueadas y renovaciones próximas
- Memoria de conversación (recuerda el contexto entre mensajes)
- Control de acceso por whitelist con flujo de solicitud/aprobación
- Reindexación automática cada 8 horas

### Repositorio

- **URL:** https://github.com/ali-cirujano-as/agente_notion
- **Rama principal:** main
- **Rama histórica (versión VM):** legacy-vm

---

## 2. Arquitectura (Cloud Run)

### Infraestructura

| Servicio | Recurso | Detalle |
|----------|---------|---------|
| Cloud Run | aws-info-bot | Servicio HTTP para el bot AWS |
| Cloud Run | gcp-info-bot | Servicio HTTP para el bot GCP |
| Cloud Storage | agentes-bizops-data | Bucket para índices, whitelists y logs |
| Secret Manager | 9 secretos | Tokens de Slack, Notion, Gemini, etc. |
| Proyecto GCP | agentes-notion-bizops | Proyecto donde está todo desplegado |
| Región | europe-southwest1 | Madrid |

### URLs de los servicios

- **AWS:** https://aws-info-bot-804310141282.europe-southwest1.run.app
- **GCP:** https://gcp-info-bot-804310141282.europe-southwest1.run.app
- **Health check:** `GET /health` → `{"status": "ok"}`
- **Reindexación manual:** `POST /reindex` con header `Authorization: Bearer <token>`

### Configuración Cloud Run

| Parámetro | Valor |
|-----------|-------|
| Memoria | 256Mi |
| CPU | 1 |
| Min instances | 1 (siempre vivo) |
| Max instances | 3 |
| Timeout | 300s |
| Puerto | 8080 |

### Flujo de un mensaje

1. Usuario escribe en Slack (DM al bot)
2. Slack envía HTTP POST a Cloud Run (`/slack/events`)
3. Cloud Run verifica signing secret
4. Responde HTTP 200 inmediatamente (< 3s)
5. En background: identifica usuario por email, busca en índice, ejecuta agente Gemini
6. Envía respuesta al usuario vía `chat_postMessage`

### Separación de datos AWS vs GCP

La base de datos "Seguimiento Comercial" en Notion contiene datos de AWS, GCP y GWS mezclados. Cada bot filtra automáticamente por la columna "Cloud":

- **AWS Info Bot:** solo filas con Cloud = "AWS"
- **Google Info Bot:** solo filas con Cloud = "GCP" o "GWS"

Si una base de datos no tiene columna "Cloud" (como Licencias Caducadas), se incluye en el bot que tenga acceso.

---

## 3. Cómo Usar los Bots

### Empezar

1. Busca "aws_info_bot" o "google_info_bot" en Slack
2. Abre un mensaje directo
3. Escribe tu pregunta

### Ejemplos de consultas

- "¿Qué provisiones están bloqueadas?"
- "¿Cuáles son mis provisiones?" (filtra por tu email)
- "Dame las provisiones de Pablo Cristobal"
- "¿Qué licencias están caducadas?"
- "¿Qué renovaciones se aproximan?"
- "¿Cómo creo una MPA dedicada?"
- "Reindexa la documentación"

### Cuando hay muchos resultados (>30)

El bot pregunta: "Hay X registros. ¿Quieres filtrar por comercial, cliente, estado o urgencia?"

Responde con el filtro: "las de Pablo", "las urgentes", "las del cliente PRISA"

### Resumen diario

Cada día a las 9:00 AM (hora España), los usuarios de la whitelist reciben un DM con:
- Sus provisiones bloqueadas
- Sus renovaciones próximas

Solo muestra lo asignado a cada usuario (por email).

---

## 4. Administración

### Administradores actuales

IDs de Slack: `U05R4UAD1RT`, `U054U2B51CP`, `U05586A67QA`, `U07JVBWAY59`

Configurados en la variable de entorno `SLACK_ADMIN_USERS`.

### Comandos de administración

Escribir directamente en el DM con el bot:

- `admin lista` → ver usuarios con acceso
- `admin añadir @usuario` → dar acceso
- `admin quitar @usuario` → quitar acceso

### Diferencia entre admin y usuario

- **Admin:** puede usar el bot + gestionar whitelist. Se configura en `SLACK_ADMIN_USERS` (requiere redeploy).
- **Usuario:** solo puede hacer consultas. Se añade con "admin añadir @usuario" desde Slack.

### Flujo de solicitud de acceso

1. Usuario sin acceso escribe al bot
2. Bot muestra botón "Solicitar acceso"
3. Usuario hace clic
4. Admins reciben DM con botones Aprobar/Rechazar
5. Admin aprueba → usuario recibe notificación y ya puede usar el bot

---

## 5. Integraciones de Notion

### Integraciones

| Integración | Variable | Qué accede |
|-------------|----------|-----------|
| ADK AWS | NOTION_TOKEN_AWS | Documentación y BDs de AWS |
| ADK GOO | NOTION_TOKEN_GCP | Documentación y BDs de GCP/GWS |

### Bases de datos compartidas

**Con ADK AWS:**
- Listado de Provisiones Bloqueadas (filtrado Cloud=AWS)

**Con ADK GOO:**
- Listado de Provisiones Bloqueadas (filtrado Cloud=GCP/GWS)
- Listado de Avisos de Renovación GWS
- Licencias Caducadas GWS

### Compartir nueva base de datos

1. Abre la BD en Notion
2. Tres puntos (···) → Connections → conecta ADK AWS o ADK GOO
3. Espera a la próxima reindexación (cada 8h) o fuerza una manual

### Linked databases (vistas)

La API de Notion no puede leer vistas vinculadas. Si ves una flecha ↗ en el título de la tabla, es una vista. Haz clic en la flecha para ir a la fuente y comparte ESA con la integración.

---

## 6. Despliegue y Mantenimiento

### Cómo desplegar cambios

Después de modificar código y hacer push a GitHub:

```bash
cd ~/Documents/claudecode/notion_AS/adk-python

gcloud builds submit --tag europe-southwest1-docker.pkg.dev/agentes-notion-bizops/slack-bots/bizops-bots:latest --project=agentes-notion-bizops --quiet

gcloud run deploy aws-info-bot --project=agentes-notion-bizops --region=europe-southwest1 --image=europe-southwest1-docker.pkg.dev/agentes-notion-bizops/slack-bots/bizops-bots:latest --quiet

gcloud run deploy gcp-info-bot --project=agentes-notion-bizops --region=europe-southwest1 --image=europe-southwest1-docker.pkg.dev/agentes-notion-bizops/slack-bots/bizops-bots:latest --quiet
```

### Cómo subir código a GitHub

```bash
cd ~/Documents/claudecode/notion_AS/adk-python
git add -A
git commit -m "descripción del cambio"
git push origin main
```

### Forzar reindexación

```bash
REINDEX_TOKEN=$(gcloud secrets versions access latest --secret=reindex-auth-token --project=agentes-notion-bizops)

curl -X POST "https://aws-info-bot-804310141282.europe-southwest1.run.app/reindex" -H "Authorization: Bearer $REINDEX_TOKEN"

curl -X POST "https://gcp-info-bot-804310141282.europe-southwest1.run.app/reindex" -H "Authorization: Bearer $REINDEX_TOKEN"
```

### Ver logs

```bash
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=aws-info-bot" --project=agentes-notion-bizops --limit=20 --format="value(textPayload)"
```

### Reiniciar un servicio

```bash
gcloud run services update aws-info-bot --project=agentes-notion-bizops --region=europe-southwest1 --no-traffic
gcloud run services update aws-info-bot --project=agentes-notion-bizops --region=europe-southwest1 --to-latest
```

---

## 7. Configuración Técnica

### Variables de entorno en Cloud Run

| Variable | Fuente | Descripción |
|----------|--------|-------------|
| BOT_TYPE | Env directa | "aws" o "gcp" |
| GCS_BUCKET | Env directa | agentes-bizops-data |
| SLACK_ADMIN_USERS | Env directa | IDs de admins separados por coma |
| SLACK_BOT_TOKEN | Secret Manager | Token OAuth del bot |
| SLACK_SIGNING_SECRET | Secret Manager | Signing secret de la app |
| NOTION_TOKEN_AWS/GCP | Secret Manager | Token de Notion |
| GOOGLE_API_KEY | Secret Manager | API key de Gemini |
| REINDEX_AUTH_TOKEN | Secret Manager | Token para endpoint /reindex |

### Secretos en Secret Manager

Para actualizar un secreto:

```bash
echo -n "nuevo-valor" | gcloud secrets versions add nombre-secreto --data-file=- --project=agentes-notion-bizops
```

### Cloud Storage (bucket: agentes-bizops-data)

```
gs://agentes-bizops-data/
├── aws/
│   ├── whitelist.json
│   ├── query_log.jsonl
│   └── index.json
└── gcp/
    ├── whitelist.json
    ├── query_log.jsonl
    └── index.json
```

---

## 8. Estructura del Código

Repositorio: https://github.com/ali-cirujano-as/agente_notion

```
├── main.py                    ← Entrypoint Cloud Run
├── slack_http_bot.py          ← Handler HTTP de Slack (FastAPI + slack-bolt)
├── Dockerfile                 ← Imagen Docker para Cloud Run
├── requirements.txt           ← Dependencias Python
├── deploy.sh                  ← Script de despliegue completo
├── agents/
│   ├── aws_agent/agent.py     ← Agente AWS (búsqueda + reindexación)
│   └── gcp_agent/agent.py     ← Agente GCP (búsqueda + reindexación)
├── notion_shared/
│   ├── indexer.py             ← Indexador de Notion (con GCS y cloud_filter)
│   ├── notion_client.py       ← Cliente HTTP de Notion API
│   └── text_extractor.py     ← Extractor de texto de bloques Notion
├── storage/
│   ├── gcs_client.py          ← Cliente de Cloud Storage
│   └── whitelist.py           ← Whitelist en Cloud Storage
└── DOCUMENTACION_AGENTES_BIZOPS_v2.md
```

---

## 9. Apps de Slack

### Configuración actual

Ambas apps usan **HTTP Mode** (no Socket Mode):
- Event Subscriptions activado con Request URL apuntando a Cloud Run
- Interactivity activado con la misma Request URL
- Socket Mode desactivado

### Request URLs

- **AWS:** https://aws-info-bot-804310141282.europe-southwest1.run.app/slack/events
- **GCP:** https://gcp-info-bot-804310141282.europe-southwest1.run.app/slack/events

### Scopes OAuth necesarios

`chat:write`, `im:history`, `im:read`, `im:write`, `users:read`, `users:read.email`

### Crear una nueva app de Slack (paso a paso)

1. https://api.slack.com/apps → Create New App → From scratch
2. Socket Mode → desactivar
3. Event Subscriptions → activar → Request URL → pegar URL de Cloud Run + `/slack/events`
4. Subscribe to bot events → añadir: `message.im`
5. Interactivity & Shortcuts → activar → Request URL → misma URL
6. OAuth & Permissions → Bot Token Scopes → añadir: `chat:write`, `im:history`, `im:read`, `im:write`, `users:read`, `users:read.email`
7. App Home → Messages Tab → activar + "Allow users to send messages"
8. Install App → Install to Workspace → copiar Bot User OAuth Token
9. Basic Information → copiar Signing Secret

---

## 10. Solución de Problemas

### El bot no responde

- Verificar que Cloud Run está corriendo: `curl https://aws-info-bot-804310141282.europe-southwest1.run.app/health`
- Verificar logs: `gcloud logging read` (ver sección 6)
- Verificar que la app de Slack tiene Event Subscriptions activado con la URL correcta

### El bot dice "No encontré información"

- El índice puede estar vacío. Forzar reindexación (ver sección 6)
- La documentación puede no existir en Notion
- Probar con sinónimos o términos más específicos

### Error al desplegar

- Verificar que gcloud está autenticado: `gcloud auth login`
- Verificar proyecto: `gcloud config set project agentes-notion-bizops`
- Verificar que las APIs están habilitadas

### Token de Slack inválido

- Si se reinstala la app, el token cambia
- Actualizar el secreto en Secret Manager
- Redesplegar el servicio

---

## 11. Costes Estimados

| Servicio | Coste/mes |
|----------|-----------|
| Cloud Run (2 servicios, min-instances=1, 256Mi) | ~20 EUR |
| Cloud Storage | ~0.02 EUR |
| Secret Manager | Gratis |
| Gemini API (uso moderado) | ~5-15 EUR |
| **Total** | **~25-35 EUR** |

---

## 12. Checklist para Nuevo Mantenedor

- [ ] Acceso al proyecto GCP `agentes-notion-bizops`
- [ ] Acceso al repo GitHub `ali-cirujano-as/agente_notion`
- [ ] Acceso a las apps de Slack (api.slack.com/apps)
- [ ] Acceso a las integraciones de Notion (notion.so/my-integrations)
- [ ] Entender esta documentación
- [ ] Saber desplegar (3 comandos de la sección 6)
- [ ] Saber gestionar whitelist (comandos admin en Slack)
- [ ] Saber compartir BDs de Notion con las integraciones
