#!/usr/bin/env python3
"""
Handles content rewriting using a Generative AI model with API key failover.
"""

import google.generativeai as genai
import logging
import re
import time
from pathlib import Path
from typing import Dict, Optional

from .config import AI_CONFIG, SCHEDULE_CONFIG
from .exceptions import AIProcessorError, AllKeysFailedError

logger = logging.getLogger(__name__)

# The original error was likely an IndentationError on a line at the top level.
# This code should be at the top level (no indentation).
# We use it here to log the number of keys found for diagnostics at startup.
for category, keys in AI_CONFIG.items():
    # Filter out empty/None keys before counting
    valid_keys_count = len([k for k in keys if k])
    if valid_keys_count > 0:
        logger.info(f"Found {valid_keys_count} API keys for category '{category}'.")
    else:
        logger.warning(f"No API keys found for category '{category}'.")


class AIProcessor:
    """
    Handles content rewriting using a Generative AI model with API key failover.
    """
    _prompt_template: Optional[str] = None

    def __init__(self, category: str):
        """
        Initializes the AI processor for a specific content category.

        Args:
            category: The content category (e.g., 'movies', 'series').

        Raises:
            AIProcessorError: If the category is invalid or has no API keys.
        """
        if category not in AI_CONFIG:
            