"""Cliente para extraer contenido de Notion."""
import requests
from typing import Optional


class NotionClient:
    BASE_URL = "https://api.notion.com/v1"
    NOTION_VERSION = "2022-06-28"

    def __init__(self, token: str):
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Notion-Version": self.NOTION_VERSION,
            "Content-Type": "application/json",
        }

    def _get(self, endpoint: str, params: Optional[dict] = None):
        r = requests.get(
            f"{self.BASE_URL}/{endpoint}",
            headers=self.headers,
            params=params,
            timeout=30,
        )
        r.raise_for_status()
        return r.json()

    def _post(self, endpoint: str, json_data: Optional[dict] = None):
        r = requests.post(
            f"{self.BASE_URL}/{endpoint}",
            headers=self.headers,
            json=json_data or {},
            timeout=30,
        )
        r.raise_for_status()
        return r.json()

    def search_all(self, filter_type: Optional[str] = None) -> list:
        """Busca todas las páginas y/o bases de datos accesibles."""
        results = []
        start_cursor = None
        while True:
            body = {"page_size": 100}
            if start_cursor:
                body["start_cursor"] = start_cursor
            if filter_type:
                body["filter"] = {"value": filter_type, "property": "object"}
            data = self._post("search", body)
            results.extend(data.get("results", []))
            if not data.get("has_more"):
                break
            start_cursor = data.get("next_cursor")
        return results

    def get_page(self, page_id: str) -> dict:
        return self._get(f"pages/{page_id}")

    def get_block_children(self, block_id: str) -> list:
        """Obtiene todos los bloques hijos de una página/bloque."""
        blocks = []
        start_cursor = None
        while True:
            params = {"page_size": 100}
            if start_cursor:
                params["start_cursor"] = start_cursor
            data = self._get(f"blocks/{block_id}/children", params)
            blocks.extend(data.get("results", []))
            if not data.get("has_more"):
                break
            start_cursor = data.get("next_cursor")
        return blocks

    def query_database(self, database_id: str) -> list:
        """Obtiene todas las filas de una base de datos."""
        rows = []
        start_cursor = None
        while True:
            body = {"page_size": 100}
            if start_cursor:
                body["start_cursor"] = start_cursor
            data = self._post(f"databases/{database_id}/query", body)
            rows.extend(data.get("results", []))
            if not data.get("has_more"):
                break
            start_cursor = data.get("next_cursor")
        return rows

    def get_database(self, database_id: str) -> dict:
        return self._get(f"databases/{database_id}")
