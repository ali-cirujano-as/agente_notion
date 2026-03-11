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

indexer = NotionIndexer(NOTION_TOKEN, INDEX_PATH)


def search_gcp_docs(query: str) -> dict:
    """Busca información sobre procesos GCP en la documentación de Notion.

    Args:
        query: La pregunta o términos de búsqueda sobre GCP.

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

    formatted = []
    for r in results:
        formatted.append({
            "title": r["title"],
            "type": r["type"],
            "content": r["content"][:2000],
            "url": r["url"],
        })
    return {"status": "ok", "results": formatted}


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
    model="gemini-2.0-flash",
    name="gcp_agent",
    description="Agente experto en procesos GCP de la organización.",
    instruction="""Eres un asistente experto en los procesos y documentación
GCP de la organización. Tu conocimiento proviene de la documentación
almacenada en Notion.

Cuando te hagan una pregunta:
1. Usa la herramienta search_gcp_docs para buscar información relevante.
2. Responde de forma clara y estructurada basándote en los resultados.
3. Si encuentras URLs de Notion, inclúyelas como referencia.
4. Si no encuentras información, dilo claramente y sugiere que se
   actualice el índice con reindex_gcp_docs.
5. Responde siempre en español.

Si te piden reindexar o actualizar la documentación, usa reindex_gcp_docs.""",
    tools=[search_gcp_docs, reindex_gcp_docs],
)
