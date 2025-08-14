import logging
import time
from datetime import datetime, timedelta

from .store import Database

logger = logging.getLogger(__name__)


class CleanupManager:
    """Handles periodic cleanup of old database records."""

    def __init__(self, cleanup_after_hours: int):
        """
        Initializes the CleanupManager.

        Args:
            cleanup_after_hours: The age in hours after which records should be deleted.
        """
        self.db = Database()
        self.cleanup_delta = timedelta(hours=cleanup_after_hours)

    def