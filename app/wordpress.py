"""
WordPress client for publishing content via the REST API.
"""

import logging
import httpx
import os
from typing import List, Dict, Any, Optional
import mimetypes
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup
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

    def _handle_featured_media(self, content_html: str, title: str) -> Optional[int]:
        """
        Parses HTML to find the first image, uploads it, and returns its media ID.

        Args:
            content_html: The HTML content of the post.
            title: The title of the post, for image metadata.

        Returns:
            The WordPress media ID of the uploaded image, or None.
        """
        try:
            soup = BeautifulSoup(content_html, 'html.parser')
            first_image = soup.find('img')

            if not first_image or not first_image.get('src'):
                logger.warning("No <img> tag found in the content to set as featured image.")
                return None

            image_url = first_image['src']
            # Ensure URL is absolute, as it might be relative in the content
            if not urlparse(image_url).scheme:
                 image_url = urljoin(self.get_domain(), image_url)

            return self.upload_media(image_url, title)
        except Exception as e:
            logger.error(f"Error processing content for featured image: {e}", exc_info=True)
            return None

    def upload_media(self, image_url: str, post_title: str) -> Optional[int]:
        """
        Downloads an image from a URL and uploads it to the WordPress media library.

        Args:
            image_url: The URL of the image to download.
            post_title: The title of the post, used for image alt text and title.

        Returns:
            The media ID of the uploaded image, or None on failure.
        """
        if not image_url:
            return None

        try:
            logger.info(f"Downloading image for upload: {image_url}")
            with self.client.stream("GET", image_url, timeout=20.0) as response:
                response.raise_for_status()
                image_data = response.read()
                content_type = response.headers.get('content-type', 'image/jpeg')
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            logger.error(f"Failed to download image from {image_url}: {e}")
            return None

        if not image_data:
            logger.warning(f"Downloaded image from {image_url} is empty.")
            return None

        parsed_url = urlparse(image_url)
        filename = os.path.basename(parsed_url.path) or f"{slugify(post_title)}.jpg"

        media_endpoint = f"{self.base_url}/media"
        headers = {
            'Content-Disposition': f'attachment; filename="{filename}"',
            'Content-Type': content_type
        }

        try:
            logger.info(f"Uploading image '{filename}' to WordPress.")
            upload_response = self.client.post(media_endpoint, content=image_data, headers=headers, timeout=60.0)
            upload_response.raise_for_status()

            media_data = upload_response.json()
            media_id = media_data['id']
            logger.info(f"Image uploaded successfully. Media ID: {media_id}")

            # Update alt text and title for SEO
            update_payload = {'alt_text': post_title, 'title': post_title}
            self.client.post(f"{media_endpoint}/{media_id}", json=update_payload)

            return media_id
        except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as e:
            logger.error(f"Failed to upload image '{filename}' to WordPress: {e}")
            if hasattr(e, 'response'):
                logger.error(f"Response body: {e.response.text}")
            return None

    def create_post(self, post_data: Dict[str, Any]) -> Optional[int]:
        """
        Creates a new post in WordPress, handling featured media automatically.

        Args:
            post_data: A dictionary containing post details like title, content, etc.

        Returns:
            The ID of the newly created post, or None on failure.
        """
        endpoint = f"{self.base_url}/posts"

        # Handle featured media by extracting it from the content
        content_html = post_data.get('content', '')
        post_title = post_data.get('title', 'Untitled Post')
        if content_html:
            media_id = self._handle_featured_media(content_html, post_title)
            if media_id:
                post_data['featured_media'] = media_id
        
        # Resolve tag names to IDs
        tag_names = post_data.get('tags', [])
        if tag_names:
            post_data['tags'] = self._get_tag_ids(tag_names)

        logger.info(f"Creating WordPress post: {post_data.get('title

    def close(self):
        """Closes the httpx client session."""
        if self.client and not self.client.is_closed:
            self.client.close()
            logger.info("WordPress client connection closed.")
