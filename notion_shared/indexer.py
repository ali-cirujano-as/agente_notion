"""Indexador de contenido de Notion a JSON local o Cloud Storage."""
import json
import os
import logging
from datetime import datetime
from typing import Optional, TYPE_CHECKING
from .notion_client import NotionClient
from .text_extractor import (
    extract_block_text,
    extract_page_title,
    extract_database_row,
    extract_property_value,
)

if TYPE_CHECKING:
    from storage.gcs_client import GCSClient

logger = logging.getLogger(__name__)


class NotionIndexer:
    def __init__(self, token: str, index_path: str, cloud_filter: Optional[list] = None):
        self.client = NotionClient(token)
        self.index_path = index_path
        self.documents: list = []
        # Si se especifica, solo indexa filas de BD cuya columna "Cloud" coincida
        self.cloud_filter = [c.lower() for c in cloud_filter] if cloud_filter else None

    def _row_matches_cloud(self, row: dict) -> bool:
        """Comprueba si una fila de BD pasa el filtro de cloud."""
        if not self.cloud_filter:
            return True
        props = row.get("properties", {})
        # Si la fila no tiene columna "Cloud", incluirla (no filtrar)
        if "Cloud" not in props:
            return True
        cloud_val = extract_property_value(props["Cloud"]).lower()
        # Si el valor está vacío, incluirla
        if not cloud_val:
            return True
        return cloud_val in self.cloud_filter

    def _extract_page_content(self, page_id: str, depth: int = 0) -> str:
        """Extrae recursivamente el contenido de una página, incluyendo BDs embebidas."""
        if depth > 3:
            return ""
        blocks = self.client.get_block_children(page_id)
        lines = []
        for block in blocks:
            btype = block.get("type", "")

            # Si es una base de datos hija (child_database), extraer sus filas
            if btype == "child_database":
                db_title = block.get("child_database", {}).get("title", "")
                try:
                    rows = self.client.query_database(block["id"])
                    row_texts = []
                    for row in rows:
                        if not self._row_matches_cloud(row):
                            continue
                        row_text = extract_database_row(row)
                        if row_text:
                            row_texts.append(row_text)
                    if row_texts:
                        lines.append(f"\n## Base de datos: {db_title}")
                        lines.extend(row_texts)
                        logger.info(f"    Extraídas {len(row_texts)} filas de BD embebida: {db_title}")
                except Exception as e:
                    logger.warning(f"    Error extrayendo BD embebida {block['id']}: {e}")
                continue

            # Recurrir dentro de synced_block (pueden contener BDs u otro contenido)
            if btype == "synced_block":
                synced_data = block.get("synced_block", {})
                synced_from = synced_data.get("synced_from")
                # Solo explorar si es el bloque original (synced_from=None)
                # o si tiene hijos
                if block.get("has_children"):
                    child_text = self._extract_page_content(
                        block["id"], depth + 1
                    )
                    if child_text:
                        lines.append(child_text)
                continue

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

        # Indexar páginas (ignorar filas de BD, ya se extraen como BD embebida)
        pages = self.client.search_all(filter_type="page")
        real_pages = [p for p in pages if p.get("parent", {}).get("type") != "database_id"]
        logger.info(f"Encontradas {len(pages)} páginas ({len(pages) - len(real_pages)} son filas de BD, se omiten)")
        for page in real_pages:
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
                    if not self._row_matches_cloud(row):
                        continue
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

    def _save_index(self, gcs_client: "Optional[GCSClient]" = None, gcs_path: Optional[str] = None):
        """Guarda el índice localmente y opcionalmente en Cloud Storage.

        Args:
            gcs_client: Cliente de Cloud Storage. Si se proporciona junto con
                gcs_path, el índice se sube también a GCS.
            gcs_path: Ruta dentro del bucket (e.g. "aws/index.json").
        """
        data = {
            "indexed_at": datetime.now().isoformat(),
            "total_documents": len(self.documents),
            "documents": self.documents,
        }

        # Siempre guardar localmente para desarrollo
        os.makedirs(os.path.dirname(self.index_path), exist_ok=True)
        with open(self.index_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        # Si se proporciona GCS, subir también al bucket
        if gcs_client is not None and gcs_path is not None:
            self.save_index_to_gcs(gcs_client, gcs_path)

    def save_index_to_gcs(self, gcs_client: "GCSClient", gcs_path: str) -> None:
        """Sube el índice actual a Cloud Storage.

        Args:
            gcs_client: Cliente de Cloud Storage inicializado.
            gcs_path: Ruta dentro del bucket (e.g. "aws/index.json").

        Raises:
            GCSError: Si la escritura a Cloud Storage falla.
        """
        data = {
            "indexed_at": datetime.now().isoformat(),
            "total_documents": len(self.documents),
            "documents": self.documents,
        }
        gcs_client.write_json(gcs_path, data)
        logger.info(f"Índice subido a GCS: {gcs_path} ({len(self.documents)} documentos)")

    @staticmethod
    def load_index_from_gcs(gcs_client: "GCSClient", gcs_path: str) -> list[dict]:
        """Carga el índice desde Cloud Storage.

        Args:
            gcs_client: Cliente de Cloud Storage inicializado.
            gcs_path: Ruta dentro del bucket (e.g. "aws/index.json").

        Returns:
            Lista de documentos del índice, o lista vacía si no existe.

        Raises:
            GCSError: Si Cloud Storage no está disponible.
        """
        data = gcs_client.read_json(gcs_path)
        if data is None:
            logger.warning(f"Índice no encontrado en GCS: {gcs_path}")
            return []
        documents = data.get("documents", [])
        logger.info(f"Índice cargado desde GCS: {gcs_path} ({len(documents)} documentos)")
        return documents

    def load_index(self) -> list[dict]:
        if os.path.exists(self.index_path):
            with open(self.index_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.documents = data.get("documents", [])
                return self.documents
        return []

    # Sinónimos y variantes para mejorar la búsqueda
    SYNONYMS = {
        "caducidad": ["caducadas", "caducado", "renewal", "renovación", "expiración", "vencimiento", "vencidas"],
        "caducadas": ["caducidad", "caducado", "renewal", "renovación", "expiración", "vencimiento", "vencidas"],
        "renovación": ["renewal", "renovaciones", "renovar", "caducadas", "caducidad"],
        "renovaciones": ["renewal", "renovación", "renovar", "avisos"],
        "bloqueadas": ["bloqueados", "bloqueada", "bloqueado", "bloqueo"],
        "bloqueados": ["bloqueadas", "bloqueada", "bloqueado", "bloqueo"],
        "provisiones": ["provisión", "provision", "provisioning"],
        "licencias": ["licencia", "suscripciones", "suscripción"],
        "facturación": ["factura", "facturas", "billing", "consumo", "consumos", "facturacion"],
        "facturacion": ["facturación", "factura", "facturas", "billing", "consumo", "consumos"],
        "soporte": ["support", "incidencia", "incidencias", "ticket", "tickets"],
        "cliente": ["clientes", "customer"],
        "clientes": ["cliente", "customer"],
        "billing": ["facturación", "factura", "consumo"],
    }

    @staticmethod
    def _normalize(text: str) -> str:
        """Elimina tildes para búsqueda flexible."""
        replacements = {
            "á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u",
            "ü": "u", "ñ": "n",
        }
        for k, v in replacements.items():
            text = text.replace(k, v)
        return text

    def _expand_keywords(self, keywords: list) -> list:
        """Expande keywords con sinónimos."""
        expanded = list(keywords)
        for kw in keywords:
            if kw in self.SYNONYMS:
                expanded.extend(self.SYNONYMS[kw])
        return list(set(expanded))

    def search(self, query: str) -> list[dict]:
        """Búsqueda por keywords en el contenido indexado."""
        if not self.documents:
            self.load_index()
        query_lower = self._normalize(query.lower())
        keywords = [kw for kw in query_lower.split() if len(kw) > 2]
        expanded = self._expand_keywords(keywords)

        # Si la query es muy genérica (1-2 palabras), devolver más resultados
        max_results = 10 if len(keywords) <= 2 else 5

        results = []
        for doc in self.documents:
            text = self._normalize(f"{doc['title']} {doc['content']}".lower())
            # Puntuar con keywords originales (peso 2) + sinónimos (peso 1)
            score = sum(2 for kw in keywords if kw in text)
            score += sum(1 for kw in expanded if kw not in keywords and kw in text)
            if score > 0:
                # Bonus para bases de datos (contienen datos reales)
                if doc.get("type") == "database":
                    score += 5
                # Bonus si el título coincide directamente con la query
                title_lower = self._normalize(doc["title"].lower())
                title_score = sum(3 for kw in keywords if kw in title_lower)
                score += title_score
                results.append({**doc, "_score": score})

        # Si hay pocos resultados para una query genérica, incluir todos
        if len(results) < 3 and len(self.documents) > 0 and len(keywords) <= 3:
            for doc in self.documents:
                if not any(r["id"] == doc["id"] for r in results):
                    results.append({**doc, "_score": 0})

        results.sort(key=lambda x: x["_score"], reverse=True)
        return results[:max_results]
