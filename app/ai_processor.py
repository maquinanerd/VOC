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
    
    def __init__(self, ai_config: Dict[str, List[str]]):
        self.ai_config = ai_config
        self.prompt_template = self._load_prompt_template()
        self._active_clients = {}  # Cache for active clients
        
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
    
    def _build_prompt(self, title: str, excerpt: str, content: str, tags_text: str) -> str:
        """Build the complete prompt by substituting placeholders"""
        return self.prompt_template.format(
            title=title,
            excerpt=excerpt,
            tags_text=tags_text,
            content=content
        )
    
    def _parse_ai_response(self, response: str) -> Optional[Dict[str, str]]:
        """Parse AI response into structured format"""
        try:
            # Look for the required sections
            sections = {}
            
            # Parse "Novo Título:"
            title_match = response.find("Novo Título:")
            if title_match != -1:
                title_start = title_match + len("Novo Título:")
                title_end = response.find("Novo Resumo:", title_start)
                if title_end == -1:
                    title_end = response.find("Novo Conteúdo:", title_start)
                if title_end != -1:
                    sections['title'] = response[title_start:title_end].strip()
            
            # Parse "Novo Resumo:"
            excerpt_match = response.find("Novo Resumo:")
            if excerpt_match != -1:
                excerpt_start = excerpt_match + len("Novo Resumo:")
                excerpt_end = response.find("Novo Conteúdo:", excerpt_start)
                if excerpt_end != -1:
                    sections['excerpt'] = response[excerpt_start:excerpt_end].strip()
            
            # Parse "Novo Conteúdo:"
            content_match = response.find("Novo Conteúdo:")
            if content_match != -1:
                content_start = content_match + len("Novo Conteúdo:")
                sections['content'] = response[content_start:].strip()
            
            # Validate all sections are present
            required_sections = ['title', 'excerpt', 'content']
            for section in required_sections:
                if section not in sections or not sections[section]:
                    logger.error(f"Missing or empty section: {section}")
                    return None
            
            return sections
            
        except Exception as e:
            logger.error(f"Error parsing AI response: {str(e)}")
            return None
    
    def rewrite_content(self, title: str, excerpt: str, content: str, tags_text: str, category: str) -> Optional[Dict[str, str]]:
        """Rewrite content using AI with the specified category"""
        logger.info(f"Processing content with AI for category: {category}")
        
        # Build the complete prompt
        prompt = self._build_prompt(title, excerpt, content, tags_text)
        
        # Try to get response from AI
        response = self._try_category_keys(category, prompt)
        if not response:
            logger.error("Failed to get response from any AI API key")
            return None
        
        # Parse the response
        parsed_response = self._parse_ai_response(response)
        if not parsed_response:
            logger.error("Failed to parse AI response")
            return None
        
        logger.info("Successfully processed content with AI")
        return parsed_response
