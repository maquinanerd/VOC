import logging
import re
import time
from typing import Dict, Any, Optional

import google.generativeai as genai
from google.api_core import exceptions

from .keys import KeyPool
from .config import AI_CONFIG, PROMPT_FILE_PATH, SCHEDULE_CONFIG, AI_MODELS, AI_GENERATION_CONFIG

logger = logging.getLogger(__name__)


class AIProcessor:
    """
    Handles content rewriting using the Gemini AI API.
    Manages API key rotation, failover, and rate limiting.
    """

    def __init__(self):
        self.key_pools = {
            category: KeyPool(api_keys)
            for category, api_keys in AI_CONFIG.items()
            if api_keys
        }
        self.prompt_template = self._load_prompt_template()
        self.generation_config = AI_GENERATION_CONFIG
        self.safety_settings = [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
        ]

    def _load_prompt_template(self) -> str:
        """Loads the prompt template from the external file."""
        try:
            with open(PROMPT_FILE_PATH, 'r', encoding='utf-8') as f:
                logger.info(f"Successfully loaded prompt template from {PROMPT_FILE_PATH}")
                return f.read()
        except FileNotFoundError:
            logger.critical(f"Prompt file not found at {PROMPT_FILE_PATH}. The application cannot proceed.")
            raise

    def rewrite_content(self, **kwargs: Any) -> Optional[str]:
        """
        Rewrites content using the AI, handling key rotation and retries.

        Args:
            **kwargs: Placeholders for the prompt template (must include 'category',
                      'title', 'content', etc.).

        Returns:
            The raw rewritten text from the AI, or None if it fails.
        """
        category = kwargs.get('category')
        if category not in self.key_pools:
            logger.error(f"Invalid or missing AI category: '{category}'. No key pool available.")
            return None

        key_pool = self.key_pools[category]
        if not key_pool._key_list: # Check if the key list for this category is empty
            logger.error(f"No API keys configured for category '{category}'.")
            return None

        prompt = self.prompt_template.format(**kwargs)
        for _ in range(len(key_pool._key_list)):
            api_key = key_pool.get_key()
            if not api_key:
                logger.warning(f"All API keys for category '{category}' are in cooldown. Will retry in the next cycle.")
                # Se get_key() retorna None, todas as chaves estão em cooldown.
                break

            try:
                logger.info(f"Attempting to rewrite content with key ending in '...{api_key[-4:]}' for category '{category}'.")
                genai.configure(api_key=api_key)
                model = genai.GenerativeModel(
                    model_name=AI_MODELS['primary'],
                    generation_config=self.generation_config,
                    safety_settings=self.safety_settings
                )
                response = model.generate_content(prompt)

                # Check for empty or blocked response
                if not response.parts:
                    logger.warning(f"AI response was empty or blocked for key ...{api_key[-4:]}. Reason: {response.prompt_feedback.block_reason}")
                    key_pool.report_failure(api_key)
                    continue # Try next key

                logger.info(f"Successfully received AI response with key ...{api_key[-4:]}.")
                key_pool.report_success(api_key)
                return response.text

            except exceptions.ResourceExhausted as e:
                logger.warning(f"AI API call failed for key ...{api_key[-4:]} with ResourceExhausted (429) error: {e}. Placing key in cooldown.")
                key_pool.report_
            except Exception as e:
                logger.error(f"An unexpected error occurred during AI processing with key ...{api_key[-4:]}: {e}")
                key_pool.report_failure(api_key)
                continue

        logger.error(f"All API keys for category '{category}' failed or are in cooldown for this cycle.")
        return None