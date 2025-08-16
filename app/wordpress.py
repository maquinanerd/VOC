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
            
        raw_url = config['url'].rstrip('/')
        self.auth = (config['user'], config['password'])
        self.categories_map = categories_map
        self.client = httpx.Client(auth=self.auth, timeout=30.0, follow_redirects=True)
        self.base_url = self._get_final_url(raw_url)

    def _get_final_url(self, url: str) -> str:
        """
        Resolves any redirects to get the final, canonical URL for the API.
        This prevents issues with POST requests being converted to GET on 301 redirects.
        """
        try:
            # Make a HEAD request to efficiently get the final URL after redirects
            response = self.client.head(url)
            final_url = str(response.url)
            if url != final_url:
                logger.warning(f"WordPress URL redirected from {url} to {final_url}. Using final URL.")
            return final_url
        except httpx.RequestError as e:
            logger.error(f"Could not resolve WordPress URL {url}. Sticking with original. Error: {e}")
            return url

    def get_domain(self) -> str:
        """Extracts the domain from the WordPress URL."""
        try:
            parsed_url = urlparse(self.base_url)
            return f"{parsed_url.scheme}://{parsed_url.netloc}"
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
            if response.status_code == 200 and response.json():
                return response.json()[0]['id']
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
        Creates a new post in WordPress.

        Args:
            post_data: A dictionary containing post details like title, content, etc.

        Returns:
            The ID of the newly created post, or None on failure.
        """
        endpoint = f"{self.base_url}/posts"
        
        # Resolve tag names to IDs
        tag_names = post_data.get('tags', [])
        if tag_names:
            post_data['tags'] = self._get_tag_ids(tag_names)

        logger.info(f"Creating WordPress post: {post_data.get('title', 'No Title')}")
        
        try:
            response = self.client.post(endpoint, json=post_data)
            
            if response.status_code == 201:
                logger.info(f"Post created successfully with ID: {response.json()['id']}")
                return response.json()['id']
            else:
                logger.error(f"Failed to create post: {response.status_code} - {response.text}")
                # Fallback attempt without metadata as per original prompt
                if 'meta' in post_data:
                    logger.info("Retrying without meta data")
                    del post_data['meta']
                    response = self.client.post(endpoint, json=post_data)
                    if response.status_code == 201:
                        logger.info(f"Post created successfully on retry with ID: {response.json()['id']}")
                        return response.json()['id']
                    else:
                         logger.error(f"Retry also failed: {response.status_code} - {response.text}")
                return None

        except (httpx.RequestError, ValueError) as e:
            logger.critical(f"An exception occurred while creating post: {e}")
            return None

    def upload_media(self, image_url: str, image_name: str) -> Optional[int]:
        """
        Downloads an image from a URL and uploads it to the WordPress media library.

        Args:
            image_url: The URL of the image to download.
            image_name: The desired filename for the uploaded image.

        Returns:
            The media ID of the uploaded image, or None on failure.
        """
        # This method would be implemented for the 'download_upload' mode.
        # It involves downloading the image into memory and then POSTing it
        # to the /wp/v2/media endpoint with appropriate headers.
        logger.warning("Media upload functionality is not fully implemented yet.")
        return None

    def close(self):
        """Closes the httpx client session."""
        if self.client and not self.client.is_closed:
            self.client.close()
            logger.info("WordPress client connection closed.")
