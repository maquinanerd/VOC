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

            # Log the number of keys loaded for each category
            movies_keys_count = len(AI_CONFIG.get('movies', []))
            series_keys_count = len(AI_CONFIG.get('series', []))
            games_keys_count = len(AI_CONFIG.get('games', []))

            logger.info(
                f"Loaded {movies_keys_count} movie keys, "
                f"{series_keys_count} series keys, "
                f"{games_keys_count} game keys."
            )

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

    def rewrite_content(self, **kwargs: Any) -> tuple[Optional[str], Optional[str]]:
        """
        Rewrites content using the AI, handling key rotation and retries.

        Args:
            **kwargs: Placeholders for the prompt template (must include 'category',
                      'title', 'content', etc.).

        Returns:
            A tuple containing:
            - The raw rewritten text from the AI, or None if it fails.
            - A failure reason string if it fails, otherwise None.
        """
        category = kwargs.get('category')
        if category not in self.key_pools:
            reason = f"Invalid or missing AI category: '{category}'. No key pool available."
            logger.error(reason)
            return None, reason

        key_pool = self.key_pools[category]
        if not key_pool._key_list: # Check if the key list for this category is empty
            reason = f"No API keys configured for category '{category}'."
            logger.error(reason)
            return None, reason

        prompt = self.prompt_template.format(**kwargs)
        last_error_reason = "No available keys to attempt."

        for _ in range(len(key_pool._key_list)):
            api_key = key_pool.get_key()
            if not api_key:
                last_error_reason = f"Key pool for category '{category}' is exhausted (all keys are in cooldown)."
                logger.warning(last_error_reason)
                break

            try:
                model_name = AI_MODELS['primary']
                logger.info(f"Attempting rewrite with model '{model_name}', key '...{api_key[-4:]}', category '{category}'.")
                genai.configure(api_key=api_key)
                model = genai.GenerativeModel(
                    model_name=model_name,
                    generation_config=self.generation_config,
                    safety_settings=self.safety_settings
                )
                response = model.generate_content(prompt)

                # Check for empty or blocked response
                if not response.parts:
                    feedback = response.prompt_feedback
                    reason = feedback.block_reason.name if feedback.block_reason else "No parts in response"
                    logger.warning(f"AI response was empty or blocked for key ...{api_key[-4:]}. Reason: {reason}")
                    key_pool.report_failure(api_key)
                    continue # Try next key

                logger.info(f"Successfully received AI response with key ...{api_key[-4:]}.")
                key_pool.report_success(api_key)
                return response.text, None

            except exceptions.ResourceExhausted as e:
                last_error_reason = "API rate limit exceeded (429)."
                logger.warning(f"AI API call failed for key ...{api_key[-4:]} with ResourceExhausted (429) error. Placing key in cooldown.")
                base_cooldown = SCHEDULE_CONFIG.get('api_call_delay_seconds', 60)
                key_pool.report_failure(api_key, base_cooldown_seconds=base_cooldown)
                continue

            except (exceptions.InternalServerError, exceptions.ServiceUnavailable) as e:
                last_error_reason = f"AI service temporary error: {e}"
                logger.warning(f"AI API call failed for key ...{api_key[-4:]} with a temporary server error: {e}. Trying next key.")
                key_pool.report_failure(api_key, base_cooldown_seconds=60) # Short cooldown
                continue

            except Exception as e:
                last_error_reason = f"Unexpected AI error: {e}"
                logger.error(f"An unexpected error occurred during AI processing with key ...{api_key[-4:]}: {e}", exc_info=True)
                key_pool.report_failure(api_key) # Default cooldown
                continue

        logger.error(f"All API keys for category '{category}' failed. Reason: {last_error_reason}")
        return None, last_error_reason