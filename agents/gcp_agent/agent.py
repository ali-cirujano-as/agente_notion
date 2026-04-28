"""Agente ADK para consultas sobre procesos GCP documentados en Notion."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from dotenv import load_dotenv
from google.adk.agents import Agent

from notion_shared.indexer import NotionIndexer

load_dotenv()

NOTION_TOKEN = os.getenv("NOTION_TOKEN_GCP", "")
INDEX_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", ".data", "gcp_index.json"
)

indexer = NotionIndexer(NOTION_TOKEN, INDEX_PATH, cloud_filter=["gcp", "gws"])


def _summarize_db_row(row_text: str) -> str:
    """Extrae solo las columnas clave de una fila de BD."""
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


def search_gcp_docs(query: str) -> dict:
    """Busca información sobre procesos GCP/GWS en la documentación de Notion.

    Args:
        query: La pregunta o términos de búsqueda sobre GCP/GWS.

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
        if r["title"] in seen_titles:
            continue
        seen_titles.add(r["title"])

        content = r["content"]
        lines = content.split("\n")
        db_rows = [l for l in lines if " | " in l and "Cliente:" in l]
        total_rows = len(db_rows)

        if total_rows > 20:
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
                content = "\n".join(_summarize_db_row(r) for r in db_rows[:10])

            formatted.append({
                "title": r["title"],
                "type": r["type"],
                "total_rows": total_rows,
                "matched_rows": len(scored),
                "content": content,
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
            })
        else:
            formatted.append({
                "title": r["title"],
                "type": r["type"],
                "content": content[:2000],
            })
    return {"status": "ok", "results": formatted[:5]}


def reindex_gcp_docs() -> dict:
    """Reindexa toda la documentación GCP desde Notion.

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
    model="gemini-2.5-pro",
    name="gcp_agent",
    description="Agente experto en procesos GCP/GWS de la organización.",
    instruction="""Eres un asistente del equipo BizOps de Altostratus. Respondes consultas
sobre procesos y datos operacionales de GCP y Google Workspace (GWS) usando
la documentación de Notion.

CÓMO RESPONDER:
1. Busca SIEMPRE con search_gcp_docs antes de responder.
2. Responde con DATOS REALES (clientes, estados, nombres). Nunca expliques
   conceptos teóricos si el usuario pide datos.
3. Si un resultado tiene "total_rows" y es mayor que 30, responde:
   "Hay [X] registros de [tema]. ¿Quieres filtrar por comercial responsable,
   cliente, estado o urgencia?"
   NO muestres datos hasta que el usuario filtre.
4. Si total_rows es 30 o menos, muestra TODOS los registros directamente.
5. Cuando el usuario responda con un filtro (ej: "pablo cristobal"),
   busca con search_gcp_docs usando ese filtro y muestra los resultados.
   NO vuelvas a preguntar.
6. Si el usuario dice "dámelas todas", "sí, todas", "muéstramelas" o similar
   después de que le dijiste cuántos hay, muestra los datos que ya tienes
   en el content del resultado anterior. NO hagas una búsqueda nueva.
7. Responde en español, corto y con bullet points.
8. No incluyas enlaces ni referencias de Notion.
9. No inventes datos.
10. NUNCA hagas más de UNA pregunta seguida.

Si te piden reindexar, usa reindex_gcp_docs.""",
    tools=[search_gcp_docs, reindex_gcp_docs],
)
