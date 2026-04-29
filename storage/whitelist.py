"""Cloud-backed whitelist for authorized bot users.

Stores the whitelist as a JSON array in Cloud Storage via GCSClient.
Uses an in-memory cache to avoid repeated reads to the bucket, with
automatic cache invalidation on modifications.

Requisitos: 3.1, 3.2
"""

import logging

from .gcs_client import GCSClient, GCSError

logger = logging.getLogger(__name__)


class CloudWhitelist:
    """Whitelist of authorized users backed by Cloud Storage.

    Maintains an in-memory cache of the user set to avoid repeated
    reads to the bucket. The cache is invalidated whenever the whitelist
    is modified (add/remove).

    Args:
        gcs: GCSClient instance for bucket operations.
        prefix: Path prefix within the bucket (e.g. "aws" or "gcp").
            The whitelist file will be stored at ``{prefix}/whitelist.json``.
    """

    def __init__(self, gcs: GCSClient, prefix: str):
        self._gcs = gcs
        self._path = f"{prefix}/whitelist.json"
        self._cache: set[str] | None = None

    def _load(self) -> set[str]:
        """Load the whitelist from Cloud Storage into the cache.

        Returns:
            The set of authorized user IDs.

        Raises:
            GCSError: If Cloud Storage is not available.
        """
        data = self._gcs.read_json(self._path)
        if data is None:
            self._cache = set()
        else:
            self._cache = set(data)
        return self._cache

    def _save(self, users: set[str]) -> None:
        """Persist the whitelist to Cloud Storage and update the cache.

        Args:
            users: The complete set of user IDs to persist.

        Raises:
            GCSError: If Cloud Storage is not available.
        """
        self._gcs.write_json(self._path, sorted(users))
        self._cache = users

    def is_allowed(self, user_id: str) -> bool:
        """Check if a user is authorized.

        Loads the whitelist from Cloud Storage on first call, then uses
        the in-memory cache for subsequent checks.

        Args:
            user_id: Slack user ID to check.

        Returns:
            True if the user is in the whitelist, False otherwise.

        Raises:
            GCSError: If Cloud Storage is not available and cache is empty.
        """
        if self._cache is None:
            self._load()
        return user_id in self._cache

    def add(self, user_id: str) -> None:
        """Add a user to the whitelist.

        Persists the change to Cloud Storage immediately and invalidates
        the cache (reloads from the saved state).

        Args:
            user_id: Slack user ID to add.

        Raises:
            GCSError: If Cloud Storage is not available.
        """
        users = self._load()
        users.add(user_id)
        self._save(users)

    def remove(self, user_id: str) -> None:
        """Remove a user from the whitelist.

        Persists the change to Cloud Storage immediately and invalidates
        the cache (reloads from the saved state). No-op if the user is
        not in the whitelist.

        Args:
            user_id: Slack user ID to remove.

        Raises:
            GCSError: If Cloud Storage is not available.
        """
        users = self._load()
        users.discard(user_id)
        self._save(users)

    def list_users(self) -> set[str]:
        """Return the set of all authorized users.

        Uses the in-memory cache if available, otherwise loads from
        Cloud Storage.

        Returns:
            A copy of the set of authorized user IDs.

        Raises:
            GCSError: If Cloud Storage is not available and cache is empty.
        """
        if self._cache is None:
            self._load()
        return set(self._cache)
