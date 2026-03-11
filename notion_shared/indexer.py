"""Indexador de contenido de Notion a JSON local."""
import json
import os
import logging
from datetime import datetime
from .notion_client import NotionClient
from .text_extractor import (
    extract_block_text,
    extract_page_title,
    extract_database_row,
)

logger = logging.getLogger(__name__)


class NotionIndexer:
    def __init__(self, token: str, index_path: str):
        self.client = NotionClient(token)
        self.index_path = index_path
        self.documents: list[dict] = []

    def _extract_page_content(self, page_id: str, depth: int = 0) -> str:
        """Extrae recursivamente el contenido de una página."""
        if depth > 3:
            return ""
        blocks = self.client.get_block_children(page_id)
        lines = []
        for block in blocks:
            text = extract_block_text(block)
            if text:
                lines.append(text)
            if block.get("has_children"):
                child_text = self._extract_page_content(
                    block["id"], depth + 1
                )
                if child_text:
                    lines.append(child_text)
        return "\n".join(lines)

    def index_all(self):
        """Indexa todas las páginas y bases de datos accesibles."""
        self.documents = []
        logger.info("Buscando contenido en Notion...")

        # Indexar páginas
        pages = self.client.search_all(filter_type="page")
        logger.info(f"Encontradas {len(pages)} páginas")
        for page in pages:
            try:
                title = extract_page_title(page)
                content = self._extract_page_content(page["id"])
                if content.strip():
                    self.documents.append({
                        "id": page["id"],
                        "type": "page",
                        "title": title,
                        "content": content,
                        "url": page.get("url", ""),
                        "last_edited": page.get("last_edited_time", ""),
                    })
                    logger.info(f"  Indexada página: {title}")
            except Exception as e:
                logger.warning(f"  Error indexando página {page['id']}: {e}")

        # Indexar bases de datos
        databases = self.client.search_all(filter_type="database")
        logger.info(f"Encontradas {len(databases)} bases de datos")
        for db in databases:
            try:
                db_info = self.client.get_database(db["id"])
                db_title = ""
                title_list = db_info.get("title", [])
                if title_list:
                    db_title = title_list[0].get("plain_text", "Sin título")

                rows = self.client.query_database(db["id"])
                row_texts = []
                for row in rows:
                    row_text = extract_database_row(row)
                    if row_text:
                        row_texts.append(row_text)

                if row_texts:
                    content = f"Base de datos: {db_title}\n"
                    content += "\n".join(row_texts)
                    self.documents.append({
                        "id": db["id"],
                        "type": "database",
                        "title": db_title,
                        "content": content,
                        "url": db.get("url", ""),
                        "last_edited": db.get("last_edited_time", ""),
                    })
                    logger.info(
                        f"  Indexada BD: {db_title} ({len(rows)} filas)"
                    )
            except Exception as e:
                logger.warning(f"  Error indexando BD {db['id']}: {e}")

        self._save_index()
        logger.info(
            f"Indexación completada: {len(self.documents)} documentos"
        )
        return len(self.documents)

    def _save_index(self):
        os.makedirs(os.path.dirname(self.index_path), exist_ok=True)
        data = {
            "indexed_at": datetime.now().isoformat(),
            "total_documents": len(self.documents),
            "documents": self.documents,
        }
        with open(self.index_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load_index(self) -> list[dict]:
        if os.path.exists(self.index_path):
            with open(self.index_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.documents = data.get("documents", [])
                return self.documents
        return []

    def search(self, query: str) -> list[dict]:
        """Búsqueda simple por keywords en el contenido indexado."""
        if not self.documents:
            self.load_index()
        query_lower = query.lower()
        keywords = query_lower.split()
        results = []
        for doc in self.documents:
            text = f"{doc['title']} {doc['content']}".lower()
            score = sum(1 for kw in keywords if kw in text)
            if score > 0:
                results.append({**doc, "_score": score})
        results.sort(key=lambda x: x["_score"], reverse=True)
        return results[:5]
