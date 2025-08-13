"""
AI content processing module using Gemini API with failover
"""

import logging
import os
import time
from typing import Dict, List, Optional, Any
import json

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)


class AIProcessor:
    """AI content processor with Gemini API integration and failover"""

    def __init__(self, api_keys: Dict[str, Dict[str, List[str]]]):
        self.backup_keys = {}
        for category, config in api_keys.items():
            self.backup_keys[category] = [key for key in config['backup_keys'] if key]
        self.failed_keys = {category: set() for category in self.backup_keys.keys()}

    def _load_prompt_template(self) -> str:
        """Load the universal prompt template from file"""
        try:
            prompt_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'universal_prompt.txt')
            with open(prompt_path, 'r', encoding='utf-8') as f:
                return f.read().strip()
        except FileNotFoundError:
            logger.critical("universal_prompt.txt not found in project root")
            raise
        except Exception as e:
            logger.critical(f"Error loading prompt template: {str(e)}")
            raise

    def _get_active_client(self, api_key: str) -> Optional[genai.Client]:
        """Get or create a Gemini client for the given API key"""
        if not api_key:
            return None

        if api_key not in self._active_clients:
            try:
                self._active_clients[api_key] = genai.Client(api_key=api_key)
            except Exception as e:
                logger.error(f"Failed to create Gemini client: {str(e)}")
                return None

        return self._active_clients[api_key]

    def _call_gemini_api(self, client: genai.Client, prompt: str, max_retries: int = 3) -> Optional[str]:
        """Call Gemini API with exponential backoff retry"""
        for attempt in range(max_retries):
            try:
                response = client.models.generate_content(
                    model="gemini-2.5-pro",
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.3,
                        max_output_tokens=4000,
                    )
                )

                if response.text:
                    return response.text.strip()
                else:
                    logger.warning("Empty response from Gemini API")
                    return None

            except Exception as e:
                logger.error(f"Gemini API call failed (attempt {attempt + 1}): {str(e)}")

                # Check for rate limiting or temporary errors
                error_str = str(e).lower()
                if any(code in error_str for code in ['429', 'rate limit', '5xx', 'timeout']):
                    if attempt < max_retries - 1:
                        # Exponential backoff
                        sleep_time = (2 ** attempt) * 5
                        logger.info(f"Rate limited, waiting {sleep_time} seconds before retry")
                        time.sleep(sleep_time)
                        continue

                # For non-retryable errors, break immediately
                if any(code in error_str for code in ['400', '401', '403', 'invalid']):
                    logger.error("Non-retryable error, skipping retries")
                    break

        return None

    def _try_category_keys(self, category: str, prompt: str) -> Optional[str]:
        """Try all available API keys for a category with failover"""
        if category not in self.ai_config:
            logger.error(f"Category '{category}' not found in AI config")
            return None

        keys = self.ai_config[category]
        available_keys = [key for key in keys if key]

        if not available_keys:
            logger.error(f"No API keys available for category '{category}'")
            return None

        logger.info(f"Trying {len(available_keys)} API keys for category '{category}'")

        for i, api_key in enumerate(available_keys):
            logger.debug(f"Trying API key {i + 1}/{len(available_keys)} for {category}")

            client = self._get_active_client(api_key)
            if not client:
                continue

            result = self._call_gemini_api(client, prompt)
            if result:
                logger.info(f"Successfully processed with key {i + 1} for {category}")
                return result

            logger.warning(f"API key {i + 1} failed for {category}, trying next")

        logger.error(f"All API keys failed for category '{category}'")
        return None

    def get_api_key(self, category: str, primary_key: Optional[str] = None) -> Optional[str]:
        """Get API key - try primary first, then fallback to backup keys"""
        # Try primary key first if provided and not failed
        if primary_key and primary_key not in self.failed_keys.get(category, set()):
            primary_key_value = os.getenv(primary_key)
            if primary_key_value:
                return primary_key_value

        # Fallback to backup keys
        if category not in self.backup_keys or not self.backup_keys[category]:
            logger.error(f"No backup API keys available for category: {category}")
            return None

        available_backup_keys = [k for k in self.backup_keys[category] if k not in self.failed_keys[category]]
        if not available_backup_keys:
            logger.warning(f"All backup keys failed for category {category}, resetting failed keys")
            self.failed_keys[category].clear()
            available_backup_keys = self.backup_keys[category]

        if available_backup_keys:
            return available_backup_keys[0]

        return None


    def _build_prompt(self, title: str, excerpt: str, content: str, tags_text: str, category: str, publisher_name: str) -> str:
        """Build the complete prompt by substituting placeholders"""
        return self.prompt_template.format(
            title=title,
            excerpt=excerpt,
            tags_text=tags_text,
            content=content,
            category=category,
            publisher_name=publisher_name
        )

    def _parse_ai_response(self, response: str) -> Optional[Dict[str, str]]:
        """Parse AI response into structured format"""
        try:
            # Clean the response to find the JSON part, removing markdown fences
            json_str = response
            if '```json' in json_str:
                json_str = json_str.split('```json')[1]
            if '```' in json_str:
                json_str = json_str.split('```')[0]
            
            sections = json.loads(json_str.strip())

            # Validate all sections are present
            required_sections = ['title', 'excerpt', 'content']
            for section in required_sections:
                if section not in sections or not sections[section]:
                    logger.error(f"AI response is missing or has empty section: {section}")
                    return None
            return sections
        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode JSON from AI response: {e}. Response: {response}")
            return None
        except Exception as e:
            logger.error(f"Error parsing AI response: {str(e)}. Response: {response}")
            return None

    def rewrite_content(self, title: str, excerpt: str, content: str, tags_text: str, category: str, primary_key: Optional[str], publisher_name: str) -> Optional[Dict[str, str]]:
        """Rewrite content using AI with the specified category"""
        logger.info(f"Processing content with AI for category: {category}")

        # Build the complete prompt
        prompt = self._build_prompt(
            title=title, excerpt=excerpt, content=content, tags_text=tags_text,
            category=category, publisher_name=publisher_name
        )

        # Try to get response from AI
        api_key = self.get_api_key(category, primary_key)
        if not api_key:
            logger.error("Failed to get API key")
            return None

        client = self._get_active_client(api_key)
        if not client:
            logger.error("Failed to create Gemini client")
            return None

        response = self._call_gemini_api(client, prompt)
        if not response:
            logger.error("Failed to get response from AI API key")
            # Mark the key as failed if the call was unsuccessful
            if primary_key:
                self.failed_keys.setdefault(category, set()).add(primary_key)
            elif category in self.backup_keys and api_key in self.backup_keys[category]:
                self.failed_keys.setdefault(category, set()).add(api_key)

            return None

        # Parse the response
        parsed_response = self._parse_ai_response(response)
        if not parsed_response:
            logger.error("Failed to parse AI response")
            return None

        logger.info("Successfully processed content with AI")
        return parsed_response