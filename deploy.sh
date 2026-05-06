#!/usr/bin/env bash
# =============================================================================
# deploy.sh — Despliegue completo de los bots BizOps en Cloud Run
#
# Proyecto: agentes-notion-bizops
# Región:   europe-southwest1
#
# Este script es idempotente: puede ejecutarse múltiples veces sin efectos
# secundarios. Los recursos que ya existen se actualizan o se omiten.
#
# IMPORTANTE: No contiene valores de secretos. Los secretos deben crearse
# previamente en Secret Manager o proporcionarse como variables de entorno
# al ejecutar este script.
#
# Requisitos: 8.1, 8.2, 8.3, 8.4
# =============================================================================

set -euo pipefail

# --- Configuración -----------------------------------------------------------
PROJECT="agentes-notion-bizops"
REGION="europe-southwest1"
BUCKET_NAME="agentes-bizops-data"
SQL_INSTANCE="bizops-sessions"
SQL_DATABASE="sessions"
SQL_USER="bot_user"
AR_REPO="slack-bots"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/${AR_REPO}/bizops-bots:latest"

# Cloud Run settings
MEMORY="256Mi"
CPU="1"
MIN_INSTANCES="1"
MAX_INSTANCES="3"
TIMEOUT="300s"

# Servicios Cloud Run
SERVICE_AWS="aws-info-bot"
SERVICE_GCP="gcp-info-bot"

# Secretos en Secret Manager (nombres)
SECRET_SLACK_BOT_TOKEN_AWS="slack-bot-token-aws"
SECRET_SLACK_SIGNING_SECRET_AWS="slack-signing-secret-aws"
SECRET_SLACK_BOT_TOKEN_GCP="slack-bot-token-gcp"
SECRET_SLACK_SIGNING_SECRET_GCP="slack-signing-secret-gcp"
SECRET_NOTION_TOKEN_AWS="notion-token-aws"
SECRET_NOTION_TOKEN_GCP="notion-token-gcp"
SECRET_GOOGLE_API_KEY="google-api-key"
SECRET_DATABASE_URL="database-url"
SECRET_REINDEX_AUTH_TOKEN="reindex-auth-token"

# Cloud Scheduler
SCHEDULER_TIMEZONE="UTC"

echo "============================================="
echo " Desplegando BizOps Bots en Cloud Run"
echo " Proyecto: ${PROJECT}"
echo " Región:   ${REGION}"
echo "============================================="
echo ""

# --- Paso 1: Configurar proyecto activo --------------------------------------
echo ">>> [1/8] Configurando proyecto GCP..."
gcloud config set project "${PROJECT}" --quiet

# --- Paso 2: Crear bucket de Cloud Storage -----------------------------------
echo ""
echo ">>> [2/8] Creando bucket de Cloud Storage: ${BUCKET_NAME}..."
if gsutil ls -b "gs://${BUCKET_NAME}" &>/dev/null; then
  echo "    Bucket ya existe, omitiendo creación."
else
  gsutil mb -p "${PROJECT}" -l "${REGION}" -b on "gs://${BUCKET_NAME}"
  echo "    Bucket creado."
fi

# Crear estructura de directorios inicial (archivos vacíos si no existen)
echo "    Verificando estructura de datos en el bucket..."
for prefix in aws gcp; do
  for file in whitelist.json index.json; do
    if ! gsutil -q stat "gs://${BUCKET_NAME}/${prefix}/${file}" 2>/dev/null; then
      if [ "${file}" = "whitelist.json" ]; then
        echo '[]' | gsutil -q cp - "gs://${BUCKET_NAME}/${prefix}/${file}"
      else
        echo '{}' | gsutil -q cp - "gs://${BUCKET_NAME}/${prefix}/${file}"
      fi
      echo "    Creado: gs://${BUCKET_NAME}/${prefix}/${file}"
    fi
  done
done

# --- Paso 3: Crear instancia Cloud SQL PostgreSQL ----------------------------
echo ""
echo ">>> [3/8] Creando instancia Cloud SQL: ${SQL_INSTANCE}..."
if gcloud sql instances describe "${SQL_INSTANCE}" --project="${PROJECT}" &>/dev/null; then
  echo "    Instancia Cloud SQL ya existe, omitiendo creación."
else
  gcloud sql instances create "${SQL_INSTANCE}" \
    --project="${PROJECT}" \
    --region="${REGION}" \
    --database-version=POSTGRES_15 \
    --tier=db-f1-micro \
    --storage-type=HDD \
    --storage-size=10GB \
    --no-assign-ip \
    --network=default \
    --quiet
  echo "    Instancia Cloud SQL creada."
fi

# Crear base de datos si no existe
echo "    Verificando base de datos: ${SQL_DATABASE}..."
if gcloud sql databases describe "${SQL_DATABASE}" --instance="${SQL_INSTANCE}" --project="${PROJECT}" &>/dev/null; then
  echo "    Base de datos ya existe."
else
  gcloud sql databases create "${SQL_DATABASE}" \
    --instance="${SQL_INSTANCE}" \
    --project="${PROJECT}" \
    --quiet
  echo "    Base de datos creada."
fi

# Crear usuario si no existe
echo "    Verificando usuario: ${SQL_USER}..."
if gcloud sql users list --instance="${SQL_INSTANCE}" --project="${PROJECT}" --format="value(name)" | grep -q "^${SQL_USER}$"; then
  echo "    Usuario ya existe."
else
  gcloud sql users create "${SQL_USER}" \
    --instance="${SQL_INSTANCE}" \
    --project="${PROJECT}" \
    --password="$(openssl rand -base64 24)" \
    --quiet
  echo "    Usuario creado. IMPORTANTE: Guarda la contraseña generada y actualiza el secreto DATABASE_URL."
fi

# --- Paso 4: Crear secretos en Secret Manager --------------------------------
echo ""
echo ">>> [4/8] Verificando secretos en Secret Manager..."
SECRETS=(
  "${SECRET_SLACK_BOT_TOKEN_AWS}"
  "${SECRET_SLACK_SIGNING_SECRET_AWS}"
  "${SECRET_SLACK_BOT_TOKEN_GCP}"
  "${SECRET_SLACK_SIGNING_SECRET_GCP}"
  "${SECRET_NOTION_TOKEN_AWS}"
  "${SECRET_NOTION_TOKEN_GCP}"
  "${SECRET_GOOGLE_API_KEY}"
  "${SECRET_DATABASE_URL}"
  "${SECRET_REINDEX_AUTH_TOKEN}"
)

for secret in "${SECRETS[@]}"; do
  if gcloud secrets describe "${secret}" --project="${PROJECT}" &>/dev/null; then
    echo "    Secreto '${secret}' ya existe."
  else
    # Crear secreto vacío (el valor debe añadirse manualmente)
    echo -n "PLACEHOLDER" | gcloud secrets create "${secret}" \
      --project="${PROJECT}" \
      --replication-policy="user-managed" \
      --locations="${REGION}" \
      --data-file=- \
      --quiet
    echo "    Secreto '${secret}' creado (valor placeholder — actualizar manualmente)."
  fi
done

echo ""
echo "    NOTA: Si los secretos tienen valor 'PLACEHOLDER', actualízalos con:"
echo "      echo -n 'valor-real' | gcloud secrets versions add <nombre-secreto> --data-file=-"

# --- Paso 5: Build de la imagen Docker ---------------------------------------
echo ""
echo ">>> [5/8] Construyendo imagen Docker..."
gcloud builds submit . \
  --project="${PROJECT}" \
  --region="${REGION}" \
  --tag="${IMAGE}" \
  --quiet

echo "    Imagen construida: ${IMAGE}"

# --- Paso 6: Desplegar servicios Cloud Run -----------------------------------
echo ""
echo ">>> [6/8] Desplegando servicios Cloud Run..."

# Obtener la connection name de Cloud SQL para el conector
SQL_CONNECTION_NAME=$(gcloud sql instances describe "${SQL_INSTANCE}" \
  --project="${PROJECT}" \
  --format="value(connectionName)")

echo "    Cloud SQL connection: ${SQL_CONNECTION_NAME}"

# --- Desplegar aws-info-bot ---
echo ""
echo "    Desplegando ${SERVICE_AWS}..."
gcloud run deploy "${SERVICE_AWS}" \
  --project="${PROJECT}" \
  --region="${REGION}" \
  --image="${IMAGE}" \
  --platform=managed \
  --allow-unauthenticated \
  --memory="${MEMORY}" \
  --cpu="${CPU}" \
  --min-instances="${MIN_INSTANCES}" \
  --max-instances="${MAX_INSTANCES}" \
  --timeout="${TIMEOUT}" \
  --port=8080 \
  --set-env-vars="BOT_TYPE=aws,GCS_BUCKET=${BUCKET_NAME},SLACK_ADMIN_USERS=" \
  --set-secrets="SLACK_BOT_TOKEN=${SECRET_SLACK_BOT_TOKEN_AWS}:latest,SLACK_SIGNING_SECRET=${SECRET_SLACK_SIGNING_SECRET_AWS}:latest,NOTION_TOKEN=${SECRET_NOTION_TOKEN_AWS}:latest,GOOGLE_API_KEY=${SECRET_GOOGLE_API_KEY}:latest,DATABASE_URL=${SECRET_DATABASE_URL}:latest,REINDEX_AUTH_TOKEN=${SECRET_REINDEX_AUTH_TOKEN}:latest" \
  --add-cloudsql-instances="${SQL_CONNECTION_NAME}" \
  --quiet

echo "    ${SERVICE_AWS} desplegado."

# --- Desplegar gcp-info-bot ---
echo ""
echo "    Desplegando ${SERVICE_GCP}..."
gcloud run deploy "${SERVICE_GCP}" \
  --project="${PROJECT}" \
  --region="${REGION}" \
  --image="${IMAGE}" \
  --platform=managed \
  --allow-unauthenticated \
  --memory="${MEMORY}" \
  --cpu="${CPU}" \
  --min-instances="${MIN_INSTANCES}" \
  --max-instances="${MAX_INSTANCES}" \
  --timeout="${TIMEOUT}" \
  --port=8080 \
  --set-env-vars="BOT_TYPE=gcp,GCS_BUCKET=${BUCKET_NAME},SLACK_ADMIN_USERS=" \
  --set-secrets="SLACK_BOT_TOKEN=${SECRET_SLACK_BOT_TOKEN_GCP}:latest,SLACK_SIGNING_SECRET=${SECRET_SLACK_SIGNING_SECRET_GCP}:latest,NOTION_TOKEN=${SECRET_NOTION_TOKEN_GCP}:latest,GOOGLE_API_KEY=${SECRET_GOOGLE_API_KEY}:latest,DATABASE_URL=${SECRET_DATABASE_URL}:latest,REINDEX_AUTH_TOKEN=${SECRET_REINDEX_AUTH_TOKEN}:latest" \
  --add-cloudsql-instances="${SQL_CONNECTION_NAME}" \
  --quiet

echo "    ${SERVICE_GCP} desplegado."

# --- Paso 7: Obtener URLs de los servicios -----------------------------------
echo ""
echo ">>> [7/8] Obteniendo URLs de los servicios..."

URL_AWS=$(gcloud run services describe "${SERVICE_AWS}" \
  --project="${PROJECT}" \
  --region="${REGION}" \
  --format="value(status.url)")

URL_GCP=$(gcloud run services describe "${SERVICE_GCP}" \
  --project="${PROJECT}" \
  --region="${REGION}" \
  --format="value(status.url)")

echo "    ${SERVICE_AWS}: ${URL_AWS}"
echo "    ${SERVICE_GCP}: ${URL_GCP}"

# --- Paso 8: Crear jobs de Cloud Scheduler -----------------------------------
echo ""
echo ">>> [8/8] Configurando Cloud Scheduler para reindexación..."

# Obtener el token de reindex desde Secret Manager para el header de Scheduler
# Cloud Scheduler usará el secreto directamente en el header
REINDEX_TOKEN_VALUE=$(gcloud secrets versions access latest \
  --secret="${SECRET_REINDEX_AUTH_TOKEN}" \
  --project="${PROJECT}" 2>/dev/null || echo "")

if [ -z "${REINDEX_TOKEN_VALUE}" ] || [ "${REINDEX_TOKEN_VALUE}" = "PLACEHOLDER" ]; then
  echo "    ADVERTENCIA: El secreto '${SECRET_REINDEX_AUTH_TOKEN}' no tiene un valor real."
  echo "    Los jobs de Cloud Scheduler se crearán pero no funcionarán hasta que se actualice el secreto."
  REINDEX_TOKEN_VALUE="PLACEHOLDER"
fi

# Job: aws-info-bot reindex a las 06:00 UTC
JOB_AWS_06="reindex-aws-0600"
echo "    Creando/actualizando job: ${JOB_AWS_06}..."
if gcloud scheduler jobs describe "${JOB_AWS_06}" --location="${REGION}" --project="${PROJECT}" &>/dev/null; then
  gcloud scheduler jobs update http "${JOB_AWS_06}" \
    --location="${REGION}" \
    --project="${PROJECT}" \
    --schedule="0 6 * * *" \
    --time-zone="${SCHEDULER_TIMEZONE}" \
    --uri="${URL_AWS}/reindex" \
    --http-method=POST \
    --headers="Authorization=Bearer ${REINDEX_TOKEN_VALUE}" \
    --attempt-deadline=600s \
    --quiet
  echo "    Job actualizado."
else
  gcloud scheduler jobs create http "${JOB_AWS_06}" \
    --location="${REGION}" \
    --project="${PROJECT}" \
    --schedule="0 6 * * *" \
    --time-zone="${SCHEDULER_TIMEZONE}" \
    --uri="${URL_AWS}/reindex" \
    --http-method=POST \
    --headers="Authorization=Bearer ${REINDEX_TOKEN_VALUE}" \
    --attempt-deadline=600s \
    --quiet
  echo "    Job creado."
fi

# Job: aws-info-bot reindex a las 14:00 UTC
JOB_AWS_14="reindex-aws-1400"
echo "    Creando/actualizando job: ${JOB_AWS_14}..."
if gcloud scheduler jobs describe "${JOB_AWS_14}" --location="${REGION}" --project="${PROJECT}" &>/dev/null; then
  gcloud scheduler jobs update http "${JOB_AWS_14}" \
    --location="${REGION}" \
    --project="${PROJECT}" \
    --schedule="0 14 * * *" \
    --time-zone="${SCHEDULER_TIMEZONE}" \
    --uri="${URL_AWS}/reindex" \
    --http-method=POST \
    --headers="Authorization=Bearer ${REINDEX_TOKEN_VALUE}" \
    --attempt-deadline=600s \
    --quiet
  echo "    Job actualizado."
else
  gcloud scheduler jobs create http "${JOB_AWS_14}" \
    --location="${REGION}" \
    --project="${PROJECT}" \
    --schedule="0 14 * * *" \
    --time-zone="${SCHEDULER_TIMEZONE}" \
    --uri="${URL_AWS}/reindex" \
    --http-method=POST \
    --headers="Authorization=Bearer ${REINDEX_TOKEN_VALUE}" \
    --attempt-deadline=600s \
    --quiet
  echo "    Job creado."
fi

# Job: gcp-info-bot reindex a las 06:00 UTC
JOB_GCP_06="reindex-gcp-0600"
echo "    Creando/actualizando job: ${JOB_GCP_06}..."
if gcloud scheduler jobs describe "${JOB_GCP_06}" --location="${REGION}" --project="${PROJECT}" &>/dev/null; then
  gcloud scheduler jobs update http "${JOB_GCP_06}" \
    --location="${REGION}" \
    --project="${PROJECT}" \
    --schedule="0 6 * * *" \
    --time-zone="${SCHEDULER_TIMEZONE}" \
    --uri="${URL_GCP}/reindex" \
    --http-method=POST \
    --headers="Authorization=Bearer ${REINDEX_TOKEN_VALUE}" \
    --attempt-deadline=600s \
    --quiet
  echo "    Job actualizado."
else
  gcloud scheduler jobs create http "${JOB_GCP_06}" \
    --location="${REGION}" \
    --project="${PROJECT}" \
    --schedule="0 6 * * *" \
    --time-zone="${SCHEDULER_TIMEZONE}" \
    --uri="${URL_GCP}/reindex" \
    --http-method=POST \
    --headers="Authorization=Bearer ${REINDEX_TOKEN_VALUE}" \
    --attempt-deadline=600s \
    --quiet
  echo "    Job creado."
fi

# Job: gcp-info-bot reindex a las 14:00 UTC
JOB_GCP_14="reindex-gcp-1400"
echo "    Creando/actualizando job: ${JOB_GCP_14}..."
if gcloud scheduler jobs describe "${JOB_GCP_14}" --location="${REGION}" --project="${PROJECT}" &>/dev/null; then
  gcloud scheduler jobs update http "${JOB_GCP_14}" \
    --location="${REGION}" \
    --project="${PROJECT}" \
    --schedule="0 14 * * *" \
    --time-zone="${SCHEDULER_TIMEZONE}" \
    --uri="${URL_GCP}/reindex" \
    --http-method=POST \
    --headers="Authorization=Bearer ${REINDEX_TOKEN_VALUE}" \
    --attempt-deadline=600s \
    --quiet
  echo "    Job actualizado."
else
  gcloud scheduler jobs create http "${JOB_GCP_14}" \
    --location="${REGION}" \
    --project="${PROJECT}" \
    --schedule="0 14 * * *" \
    --time-zone="${SCHEDULER_TIMEZONE}" \
    --uri="${URL_GCP}/reindex" \
    --http-method=POST \
    --headers="Authorization=Bearer ${REINDEX_TOKEN_VALUE}" \
    --attempt-deadline=600s \
    --quiet
  echo "    Job creado."
fi

# --- Resumen final -----------------------------------------------------------
echo ""
echo "============================================="
echo " ✅ Despliegue completado"
echo "============================================="
echo ""
echo " Servicios Cloud Run:"
echo "   ${SERVICE_AWS}: ${URL_AWS}"
echo "   ${SERVICE_GCP}: ${URL_GCP}"
echo ""
echo " Endpoints de Slack (configurar en api.slack.com):"
echo "   AWS App → Request URL: ${URL_AWS}/slack/events"
echo "   GCP App → Request URL: ${URL_GCP}/slack/events"
echo ""
echo " Cloud Scheduler (4 jobs):"
echo "   ${JOB_AWS_06}: 06:00 UTC → ${URL_AWS}/reindex"
echo "   ${JOB_AWS_14}: 14:00 UTC → ${URL_AWS}/reindex"
echo "   ${JOB_GCP_06}: 06:00 UTC → ${URL_GCP}/reindex"
echo "   ${JOB_GCP_14}: 14:00 UTC → ${URL_GCP}/reindex"
echo ""
echo " Próximos pasos:"
echo "   1. Actualizar secretos con valores reales (si tienen PLACEHOLDER)"
echo "   2. Configurar Request URL en cada app de Slack"
echo "   3. Desactivar Socket Mode en cada app de Slack"
echo "   4. Activar Event Subscriptions e Interactivity"
echo "   5. Subir datos iniciales (whitelists, índices) al bucket si es necesario"
echo "============================================="
