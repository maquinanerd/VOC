"""
WordPress client for publishing content via the REST API.
"""

import logging
import httpx
from typing import List, Dict, Any, Optional
from urllib.parse import urlparse
from slugify import slugify

logger = logging.getLogger(__name__)


class WordPressClient:
    """Handles communication with the WordPress REST API."""

    def __init__(self, config: Dict[str, Any], categories_map: Dict[str, int]):
        """
        Initializes the WordPress client.

        Args:
            config: Dictionary with 'url', 'user', and 'password'.
            categories_map: Dictionary mapping category names to IDs.
        """
        if not config.get('url') or not config.get('user') or not config.get('password'):
            raise ValueError("WordPress URL, user, and password must be provided.")
            
        self.base_url = config['url'].rstrip('/')
        self.auth = (config['user'], config['password'])
        self.categories_map = categories_map
        self.client = httpx.Client(auth=self.auth, timeout=30.0, follow_redirects=True)

    def get_domain(self) -> str:
        """Extracts the domain from the WordPress URL."""
        try:
            parsed = urlparse(self.base_url)
            return f"{parsed.scheme}://{parsed.netloc}"
        except Exception:
            return self.base_url

    def _get_tag_id(self, tag_name: str) -> Optional[int]:
        """
        Gets the ID of a tag, creating it if it doesn't exist.

        Args:
            tag_name: The name of the tag.

        Returns:
            The ID of the tag, or None if it cannot be found or created.
        """
        tag_slug = slugify(tag_name)
        if not tag_slug:
            return None

        # 1. Try to find the tag by slug
        try:
            response = self.client.get(f"{self.base_url}/tags", params={'slug': tag_slug})
            if response.status_code == 200:
                json_response = response.json()
                if json_response:
                    return json_response[0]['id']
        except (httpx.RequestError, ValueError) as e:
            logger.error(f"Error searching for tag '{tag_name}': {e}")

        # 2. If not found, create it
        try:
            response = self.client.post(f"{self.base_url}/tags", json={'name': tag_name, 'slug': tag_slug})
            if response.status_code == 201:
                logger.info(f"Successfully created tag '{tag_name}'")
                return response.json()['id']
            # Handle case where tag exists but slug search failed (e.g., due to cache)
            elif response.status_code == 400 and response.json().get('code') == 'term_exists':
                logger.warning(f"Tag '{tag_name}' already exists. Retrieving its ID.")
                return response.json()['data']['term_id']
            else:
                logger.error(f"Failed to create tag '{tag_name}': {response.status_code} - {response.text}")
                return None
        except (httpx.RequestError, ValueError) as e:
            logger.error(f"Exception while creating tag '{tag_name}': {e}")
            return None

    def _get_tag_ids(self, tag_names: List[str]) -> List[int]:
        """
        Converts a list of tag names to a list of tag IDs.

        Args:
            tag_names: A list of tag names.

        Returns:
            A list of corresponding tag IDs.
        """
        tag_ids = []
        for name in tag_names:
            tag_id = self._get_tag_id(name)
            if tag_id:
                tag_ids.append(tag_id)
        return tag_ids

    def create_post(self, post_data: Dict[str, Any]) -> Optional[int]:
        """
        
            if response.status_code == 201:
                post_id = response.json()['id']
                logger.info(f"Successfully created post with ID: {post_id}")
                return post_id
            else:
                logger.error(f"Failed to create post: {response.status_code} - {response.text}")
                
                # Try without meta data if it failed
                if 'meta' in payload:
                    logger.info("Retrying without meta data")
                    del payload['meta']
                    
                    response = self.session.post(f"{self.base_url}/posts", json=payload)
                    if response.status_code == 201:
                        post_id = response.json()['id']
                        logger.info(f"Successfully created post without meta data: {post_id}")
                        return post_id
                
                return None
                
        except Exception as e:
            logger.error(f"Error creating WordPress post: {str(e)}")
            return None
    
    def update_post(self, post_id: int, post_data: Dict[str, Any]) -> bool:
        """Update an existing WordPress post"""
        try:
            response = self.session.post(f"{self.base_url}/posts/{post_id}", json=post_data)
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Error updating post {post_id}: {str(e)}")
            return False
    
    def delete_post(self, post_id: int) -> bool:
        """Delete a WordPress post"""
        try:
            response = self.session.delete(f"{self.base_url}/posts/{post_id}")
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Error deleting post {post_id}: {str(e)}")
            return False
