"""Agente ADK para consultas sobre procesos AWS documentados en Notion."""
import os
import sys

# Añadir el directorio raíz al path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from dotenv import load_dotenv
from google.adk.agents import Agent

from notion_shared.indexer import NotionIndexer

load_dotenv()

NOTION_TOKEN = os.getenv("NOTION_TOKEN_AWS", "")
INDEX_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", ".data", "aws_index.json"
)
GCS_BUCKET = os.getenv("GCS_BUCKET", "")

# Si GCS_BUCKET está configurado, cargar índice desde Cloud Storage
_gcs_client = None
_gcs_path = None
if GCS_BUCKET:
    from storage.gcs_client import GCSClient

    _gcs_client = GCSClient(GCS_BUCKET)
    _gcs_path = "aws/index.json"

indexer = NotionIndexer(
    NOTION_TOKEN,
    INDEX_PATH,
    cloud_filter=["aws"],
    gcs_client=_gcs_client,
    gcs_path=_gcs_path,
)

# Mapeo de URLs: fuente → vista que ve el comercial
# Cuando el agente responde, usa estas URLs en vez de las de la fuente
_URL_MAP = {
    "https://app.notion.com/p/1b3bbebfb49b8089a47ee16614be326b": "https://www.notion.so/altostratus-es/AWS-Listado-Provisiones-Bloqueadas-1aebbebfb49b8098b107e12b0c92a5de",
    "https://www.notion.so/1b3bbebfb49b8089a47ee16614be326b": "https://www.notion.so/altostratus-es/AWS-Listado-Provisiones-Bloqueadas-1aebbebfb49b8098b107e12b0c92a5de",
}

# URLs fijas para documentos por título (cuando la URL de la fuente no coincide)
_TITLE_URL_MAP = {
    "Listado de Provisiones Bloqueadas": "https://www.notion.so/altostratus-es/AWS-Listado-Provisiones-Bloqueadas-1aebbebfb49b8098b107e12b0c92a5de",
    "AWS - Listado Provisiones Bloqueadas": "https://www.notion.so/altostratus-es/AWS-Listado-Provisiones-Bloqueadas-1aebbebfb49b8098b107e12b0c92a5de",
    "Listado de provisiones en curso - EPPM": "https://www.notion.so/altostratus-es/Listado-de-provisiones-en-curso-EPPM-2a1bbebfb49b80448253f24cf172d70c",
}


def _map_url(title: str, url: str) -> str:
    """Reemplaza la URL de la fuente por la URL de la vista para el comercial."""
    # Primero intentar por título
    if title in _TITLE_URL_MAP:
        return _TITLE_URL_MAP[title]
    # Luego por URL directa
    if url in _URL_MAP:
        return _URL_MAP[url]
    return url


def _summarize_db_row(row_text: str) -> str:
    """Extrae solo las columnas clave de una fila de BD."""
    # Las columnas importantes para el usuario
    key_columns = [
        "Cliente", "Key", "Status", "Notas Comercial",
        "Documentación Pendiente", "Comercial Responsable Altostratus",
        "Assignee", "Urgencia", "Cloud", "Código de Oferta",
        "Fecha Fin Real", "Issue Type",
    ]
    parts = row_text.split(" | ")
    relevant = []
    for part in parts:
        for col in key_columns:
            if part.startswith(f"{col}: "):
                relevant.append(part)
                break
    return " | ".join(relevant) if relevant else row_text[:200]


def search_aws_docs(query: str) -> dict:
    """Busca información sobre procesos AWS en la documentación de Notion.

    Args:
        query: La pregunta o términos de búsqueda sobre AWS.

    Returns:
        dict con los resultados encontrados.
    """
    results = indexer.search(query)
    if not results:
        return {
            "status": "no_results",
            "message": "No encontré información relevante. "
            "Puede que el índice esté vacío. "
            "Ejecuta primero el indexador.",
        }

    query_lower = query.lower()
    keywords = [kw for kw in query_lower.split() if len(kw) > 2]

    formatted = []
    seen_titles = set()
    for r in results:
        # Evitar duplicados (misma BD aparece en varias páginas)
        if r["title"] in seen_titles:
            continue
        seen_titles.add(r["title"])

        content = r["content"]
        lines = content.split("\n")
        db_rows = [l for l in lines if " | " in l and "Cliente:" in l]
        total_rows = len(db_rows)

        if total_rows > 20:
            # BD grande: resumir filas y filtrar por keywords
            scored = []
            for line in db_rows:
                line_lower = line.lower()
                score = sum(1 for kw in keywords if kw in line_lower)
                if score > 0:
                    scored.append((score, _summarize_db_row(line)))
            scored.sort(key=lambda x: x[0], reverse=True)

            if scored:
                content = "\n".join(line for _, line in scored[:20])
            else:
                # Sin match: resumir las primeras 10
                content = "\n".join(_summarize_db_row(r) for r in db_rows[:10])

            formatted.append({
                "title": r["title"],
                "type": r["type"],
                "total_rows": total_rows,
                "matched_rows": len(scored),
                "content": content,
                "url": _map_url(r["title"], r.get("url", "")),
            })
        elif len(content) > 4000:
            scored = []
            for line in lines:
                line_lower = line.lower()
                score = sum(1 for kw in keywords if kw in line_lower)
                if score > 0:
                    scored.append((score, line))
            scored.sort(key=lambda x: x[0], reverse=True)
            if scored:
                content = "\n".join(line for _, line in scored[:15])
            else:
                content = content[:2000]
            formatted.append({
                "title": r["title"],
                "type": r["type"],
                "content": content,
                "url": _map_url(r["title"], r.get("url", "")),
            })
        else:
            formatted.append({
                "title": r["title"],
                "type": r["type"],
                "content": content[:2000],
                "url": _map_url(r["title"], r.get("url", "")),
            })
    # Filtrar: solo mantener URLs de altostratus-es y eliminar duplicadas
    seen_urls = set()
    for item in formatted:
        url = item.get("url", "")
        if not url.startswith("https://www.notion.so/altostratus-es/"):
            item["url"] = ""
        elif url in seen_urls:
            item["url"] = ""
        else:
            seen_urls.add(url)
    return {"status": "ok", "results": formatted[:5]}


def reindex_aws_docs() -> dict:
    """Reindexa toda la documentación AWS desde Notion.

    Returns:
        dict con el resultado de la indexación.
    """
    try:
        count = indexer.index_all()
        return {
            "status": "ok",
            "message": f"Indexación completada: {count} documentos.",
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


agent = Agent(
    model="gemini-2.5-flash",
    name="aws_agent",
    description="Agente experto en procesos AWS de la organización.",
    instruction="""Eres un asistente del equipo BizOps de Altostratus. Respondes consultas
sobre procesos y datos operacionales de AWS usando la documentación de Notion.

CÓMO RESPONDER:
1. Busca SIEMPRE con search_aws_docs antes de responder.
2. Responde con DATOS REALES (clientes, estados, nombres). Nunca expliques
   conceptos teóricos si el usuario pide datos.
3. Si un resultado tiene "total_rows" y es mayor que 30, responde:
   "Hay [X] registros de [tema]. ¿Quieres filtrar por comercial responsable,
   cliente, estado o urgencia?"
   NO muestres datos hasta que el usuario filtre.
4. Si total_rows es 30 o menos, muestra TODOS los registros directamente.
5. Cuando el usuario responda con un filtro (ej: "pablo cristobal"),
   busca con search_aws_docs usando ese filtro y muestra los resultados.
   NO vuelvas a preguntar.
6. Si el usuario dice "dámelas todas", "sí, todas", "muéstramelas" o similar
   después de que le dijiste cuántos hay, muestra los datos que ya tienes
   en el content del resultado anterior. NO hagas una búsqueda nueva.
7. Responde en español, corto y con bullet points.
8. Al final de tu respuesta, incluye EXACTAMENTE UN enlace a Notion.
   Elige el enlace más relevante de los resultados — el que mejor corresponda
   a la consulta del usuario. Solo usa URLs que empiecen por "https://www.notion.so/altostratus-es/".
   Formato: "📎 Ver en Notion: <url>"
   NUNCA incluyas más de un enlace. NUNCA uses URLs de "app.notion.com".
9. No inventes datos.
10. NUNCA hagas más de UNA pregunta seguida.

Si te piden reindexar, usa reindex_aws_docs.""",
    tools=[search_aws_docs, reindex_aws_docs],
)
