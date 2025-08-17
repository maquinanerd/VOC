#!/usr/bin/env python3
"""
Handles content rewriting using a Generative AI model with API key failover.
"""
import json
import google.generativeai as genai
import logging
import re
import time
from pathlib import Path 
from typing import Dict, Optional, List, Tuple, Any

from .config import AI_CONFIG, SCHEDULE_CONFIG
from .exceptions import AIProcessorError, AllKeysFailedError

logger = logging.getLogger(__name__)

# Log the number of keys found for diagnostics at startup.
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
            raise AIProcessorError(f"Invalid AI category specified: '{category}'. No configuration found.")

        self.category = category
        self.api_keys: List[str] = [key for key in AI_CONFIG.get(category, []) if key]
        if not self.api_keys:
            raise AIProcessorError(f"No valid API keys found for category '{category}'.")

        self.current_key_index = 0
        self.model = None
        self._configure_model()

    def _configure_model(self):
        """Configures the generative AI model with the current API key."""
        if self.current_key_index >= len(self.api_keys):
            raise AllKeysFailedError(f"All {len(self.api_keys)} API keys for category '{self.category}' have failed.")

        api_key = self.api_keys[self.current_key_index]
        try:
            genai.configure(api_key=api_key)
            self.model = genai.GenerativeModel('gemini-1.5-flash-latest')
            logger.info(f"Using API key index {self.current_key_index} for category '{self.category}'.")
        except Exception as e:
            logger.error(f"Failed to configure Gemini with API key index {self.current_key_index}: {e}")
            self._failover_to_next_key()
            self._configure_model()  # Retry configuration with the new key

    def _failover_to_next_key(self):
        """Switches to the next available API key."""
        self.current_key_index += 1
        logger.warning(f"Failing over to next API key for category '{self.category}'.")

    @classmethod
    def _load_prompt_template(cls) -> str:
        """Loads the universal prompt from 'universal_prompt.txt'."""
        if cls._prompt_template is None:
            try:
                # Assuming the script is run from the project root
                prompt_path = Path('universal_prompt.txt')
                if not prompt_path.exists():
                    # Fallback for when run as a module
                    prompt_path = Path(__file__).resolve().parent.parent / 'universal_prompt.txt'

                with open(prompt_path, 'r', encoding='utf-8') as f:
                    cls._prompt_template = f.read()
            except FileNotFoundError:
                logger.critical("'universal_prompt.txt' not found in the project root.")
                raise AIProcessorError("Prompt template file not found.")
        return cls._prompt_template

    def rewrite_content(
        self, title: str, excerpt: str, tags_text: str, content: str, domain: str
    ) -> Tuple[Optional[Dict[str, str]], Optional[str]]:
        """
        Rewrites the given article content using the AI model.

        Args:
            title: The original title of the article.
            excerpt: The original excerpt/summary.
            tags_text: A string of comma-separated tags.
            content: The full HTML content of the article.
            domain: The base domain for internal links.

        Returns:
            A tuple containing a dictionary with the rewritten text and a failure
            reason (or None if successful).
        """
        prompt_template = self._load_prompt_template()
        prompt = prompt_template.format(
            title=title,
            excerpt=excerpt or "N/A",
            tags_text=tags_text,
            content=content,
            domain=domain
        )

        last_error = "Unknown error"
        for _ in range(len(self.api_keys)):
            try:
                logger.info(f"Sending content to AI for rewriting (Key index: {self.current_key_index})...")
                response = self.model.generate_content(prompt)

                parsed_data = self._parse_response(response.text)
                if not parsed_data:
                    raise AIProcessorError("Failed to parse AI response into the expected format.")

                # Add a delay between successful calls to respect rate limits
                time.sleep(SCHEDULE_CONFIG.get('api_call_delay', 30))

                return parsed_data, None

            except Exception as e:
                last_error = str(e)
                logger.error(f"AI content generation failed with key index {self.current_key_index}: {last_error}")
                self._failover_to_next_key()
                if self.current_key_index < len(self.api_keys):
                    self._configure_model()
                else:
                    logger.critical("All API keys have failed.")
                    break  # Exit loop if all keys are exhausted
        
        final_reason = f"All API keys for category '{self.category}' failed. Last error: {last_error}"
        logger.critical(f"Failed to rewrite content. {final_reason}")
        return None, final_reason

    @staticmethod
    def _parse_response(text: str) -> Optional[Dict[str, str]]:
        """
        Parses the raw text response from the AI into a structured dictionary.
        """
        try:
            # Use more robust regex to handle variations in whitespace and newlines
            title_match = re.search(r"Novo Título:\s*(.*?)\s*Novo Resumo:", text, re.DOTALL | re.IGNORECASE)
            summary_match = re.search(r"Novo Resumo:\s*(.*?)\s*Novo Conteúdo:", text, re.DOTALL | re.IGNORECASE)
            content_match = re.search(r"Novo Conteúdo:\s*(.*)", text, re.DOTALL | re.IGNORECASE)

            if not (title_match and summary_match and content_match):
                logger.error("AI response did not match the expected format (Title/Summary/Content).")
                logger.debug(f"Received response: {text[:500]}...")
                return None

            rewritten = {
                'title': title_match.group(1).strip(),
                'summary': summary_match.group(1).strip(),
                'content': content_match.group(1).strip(),
            }

            if not all(rewritten.values()):
                logger.error("AI response contained empty sections.")
                return None

            logger.info("Successfully parsed AI response.")
            return rewritten

        except Exception as e:
            logger.error(f"Error parsing AI response: {e}")
            return None
