"""Cliente de Google Cloud Storage para persistir datos del bot.

Proporciona lectura/escritura de JSON y append de JSONL al bucket configurado.
Maneja errores cuando Cloud Storage no está disponible (Requisito 3.5).
"""

import json
import logging
from typing import Any

from google.cloud import storage
from google.api_core import exceptions as gcs_exceptions

logger = logging.getLogger(__name__)


class GCSError(Exception):
    """Error raised when Cloud Storage operations fail.

    Callers can catch this to handle GCS unavailability gracefully.
    """

    def __init__(self, message: str, original_error: Exception | None = None):
        super().__init__(message)
        self.original_error = original_error


class GCSClient:
    """Client for reading and writing JSON/JSONL data to a GCS bucket.

    Args:
        bucket_name: Name of the GCS bucket to use.

    Raises:
        GCSError: If the storage client cannot be initialized or the bucket
            is not accessible.
    """

    def __init__(self, bucket_name: str):
        if not bucket_name:
            raise GCSError("bucket_name must not be empty")
        self.bucket_name = bucket_name
        try:
            self._client = storage.Client()
            self._bucket = self._client.bucket(bucket_name)
        except Exception as e:
            raise GCSError(
                f"Failed to initialize Cloud Storage client for bucket '{bucket_name}': {e}",
                original_error=e,
            )

    def read_json(self, path: str) -> dict | list | None:
        """Read a JSON file from the bucket.

        Args:
            path: Object path within the bucket (e.g. "aws/whitelist.json").

        Returns:
            Parsed JSON content as dict or list, or None if the blob does not exist.

        Raises:
            GCSError: If Cloud Storage is not available or the read fails
                for reasons other than the blob not existing.
        """
        try:
            blob = self._bucket.blob(path)
            content = blob.download_as_text(encoding="utf-8")
            return json.loads(content)
        except gcs_exceptions.NotFound:
            return None
        except json.JSONDecodeError as e:
            raise GCSError(
                f"Invalid JSON in gs://{self.bucket_name}/{path}: {e}",
                original_error=e,
            )
        except Exception as e:
            raise GCSError(
                f"Failed to read gs://{self.bucket_name}/{path}: {e}",
                original_error=e,
            )

    def write_json(self, path: str, data: Any) -> None:
        """Write data as a JSON file to the bucket.

        Args:
            path: Object path within the bucket (e.g. "aws/whitelist.json").
            data: Data to serialize as JSON (must be JSON-serializable).

        Raises:
            GCSError: If Cloud Storage is not available or the write fails.
        """
        try:
            blob = self._bucket.blob(path)
            blob.upload_from_string(
                json.dumps(data, ensure_ascii=False, indent=2),
                content_type="application/json",
            )
        except Exception as e:
            raise GCSError(
                f"Failed to write gs://{self.bucket_name}/{path}: {e}",
                original_error=e,
            )

    def append_jsonl(self, path: str, entry: dict) -> None:
        """Append a single JSON entry as a new line to a JSONL file.

        If the file does not exist, it will be created. Each entry is
        serialized as a single JSON line followed by a newline character.

        Args:
            path: Object path within the bucket (e.g. "aws/query_log.jsonl").
            entry: Dictionary to append as a JSON line.

        Raises:
            GCSError: If Cloud Storage is not available or the operation fails.
        """
        try:
            blob = self._bucket.blob(path)
            existing = ""
            try:
                if blob.exists():
                    existing = blob.download_as_text(encoding="utf-8")
            except gcs_exceptions.NotFound:
                existing = ""

            new_line = json.dumps(entry, ensure_ascii=False) + "\n"
            blob.upload_from_string(
                existing + new_line,
                content_type="application/x-ndjson",
            )
        except GCSError:
            raise
        except Exception as e:
            raise GCSError(
                f"Failed to append to gs://{self.bucket_name}/{path}: {e}",
                original_error=e,
            )
