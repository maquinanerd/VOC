import logging
from typing import Any, Optional

import google.generativeai as genai
from google.api_core import exceptions

from .key_pool import KeyPool
from .config import AI_CONFIG, PROMPT_FILE_PATH, AI_MODELS, AI_GENERATION_CONFIG

logger = logging.getLogger(__name__)


class AIProcessor:
    """Handles content rewriting using the Gemini AI API."""

    def __init__(self):
        self.key_pools = {
            category: KeyPool(api_keys)
            for category, api_keys in AI_CONFIG.items()
            if api_keys
        }
        logger.info(
            "Loaded %d movie keys, %d series keys, %d game keys",
            len(AI_CONFIG.get("movies", [])),
            len(AI_CONFIG.get("series", [])),
            len(AI_CONFIG.get("games", [])),
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
        try:
            with open(PROMPT_FILE_PATH, "r", encoding="utf-8") as f:
                logger.info(
                    f"Successfully loaded prompt template from {PROMPT_FILE_PATH}"
                )
                return f.read()
        except FileNotFoundError:
            logger.critical(
                f"Prompt file not found at {PROMPT_FILE_PATH}. The application cannot proceed."
            )
            raise

    def rewrite_content(self, **kwargs: Any) -> Optional[str]:
        """Rewrites content using the AI, handling key rotation and retries."""
        category = kwargs.get("category")
        if category not in self.key_pools:
            logger.error(
                f"Invalid or missing AI category: '{category}'. No key pool available."
            )
            return None

        key_pool = self.key_pools[category]
        if not key_pool.keys:
            logger.error(
                f"No API keys configured for category '{category}'."
            )
            return None

        prompt = self.prompt_template.format(**kwargs)

        for _ in range(len(key_pool.keys)):
            api_key = key_pool.next_key()
            if not api_key:
                logger.warning(
                    f"All API keys for category '{category}' are in cooldown. Will retry in the next cycle."
                )
                break
            try:
                logger.info(
                    f"Attempting to rewrite content with key ending in '...{api_key[-4:]}' for category '{category}'."
                )
                genai.configure(api_key=api_key)
                model = genai.GenerativeModel(
                    model_name=AI_MODELS["primary"],
                    generation_config=self.generation_config,
                    safety_settings=self.safety_settings,
                )
                response = model.generate_content(prompt)
                if not response.parts:
                    logger.warning(
                        f"AI response was empty or blocked for key ...{api_key[-4:]}. Reason: {response.prompt_feedback.block_reason}"
                    )
                    key_pool.report_failure(api_key, 60)
                    continue
                key_pool.report_success(api_key)
                logger.info(
                    f"Successfully received AI response with key ...{api_key[-4:]}.")
                return response.text
            except exceptions.ResourceExhausted as e:
                logger.warning("429 on pro → trying flash")
                try:
                    genai.configure(api_key=api_key)
                    model = genai.GenerativeModel(
                        model_name=AI_MODELS["fallback"],
                        generation_config=self.generation_config,
                        safety_settings=self.safety_settings,
                    )
                    response = model.generate_content(prompt)
                    if not response.parts:
                        raise exceptions.ResourceExhausted("Empty response")
                    key_pool.report_success(api_key)
                    return response.text
                except Exception:
                    logger.warning(
                        f"report_failure key ****{api_key[-4:]} -> rotating to next key"
                    )
                    retry_delay = getattr(e, "retry_delay", 60)
                    key_pool.report_failure(api_key, retry_delay)
            except Exception as e:
                logger.error(
                    f"An unexpected error occurred during AI processing with key ...{api_key[-4:]}: {e}"
                )
                key_pool.report_failure(api_key, 60)

        logger.error(
            f"All API keys for category '{category}' failed or are in cooldown for this cycle."
        )
        return None
