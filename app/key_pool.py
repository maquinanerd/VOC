import time
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)


class KeyPool:
    """Manages a pool of API keys with rotation and exponential cooldown."""

    def __init__(self, keys: List[str]):
        self.keys = [k for k in keys if k]
        self._cooldowns = {k: 0.0 for k in self.keys}
        self._fail_counts = {k: 0 for k in self.keys}
        self._index = 0
        logger.info("KeyPool ready")

    def _is_available(self, key: str) -> bool:
        return time.time() >= self._cooldowns.get(key, 0)

    def next_key(self) -> Optional[str]:
        """Returns the next available key skipping those in cooldown."""
        if not self.keys:
            return None
        start = self._index
        now = time.time()
        for _ in range(len(self.keys)):
            key = self.keys[self._index]
            if now >= self._cooldowns.get(key, 0):
                return key
            self._index = (self._index + 1) % len(self.keys)
        return None

    def report_failure(self, key: str, retry_delay_seconds: float, hard: bool = False) -> None:
        """Put key on exponential cooldown and advance pointer."""
        if key not in self._cooldowns:
            return
        count = self._fail_counts.get(key, 0) + 1
        self._fail_counts[key] = 0 if hard else count
        base = max(retry_delay_seconds, 1)
        delay = min(base * (2 ** (count - 1)), 300)
        self._cooldowns[key] = time.time() + delay
        logger.info(f"cooldown set for key ****{key[-4:]} for {int(delay)}s")
        self._index = (self._index + 1) % len(self.keys)

    def report_success(self, key: str) -> None:
        if key in self._cooldowns:
            self._cooldowns[key] = 0
            self._fail_counts[key] = 0
        self._index = (self._index + 1) % len(self.keys)
