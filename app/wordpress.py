"""
WordPress REST API client with authentication and content management
"""

import logging
import base64
import json
from typing import Dict, Any, List, Optional
from urllib.parse import urljoin, urlparse

import requests

logger = logging.getLogger(__name__)


class WordPressClient:
    """WordPress REST API client"""
    
    def __init__(self, wp_config: Dict[str, str], wp_categories: Dict[str, int]):
        self.config = wp_config
        self.categories = wp_categories
        self.session = requests.Session()
        
        # Set up authentication
        if wp_config.get('user') and wp_config.get('password'):
            auth_string = f"{wp_config['user']}:{wp_config['password']}"
            auth_bytes = auth_string.encode('ascii')
            auth_b64 = base64.b64encode(auth_bytes).decode('ascii')
            self.session.headers.update({
                'Authorization': f'Basic {auth_b64}',
                'Content-Type': 'application/json'
            })
        
        # Base API URL
        self.base_url = wp_config.get('url', '').rstrip('/')
        if not self.base_url.endswith('/wp-json/wp/v2'):
            if self.base_url.endswith('/wp-json/wp/v2/'):
                self.base_url = self.base_url.rstrip('/')
            else:
                self.base_url = urljoin(self.base_url, '/wp-json/wp/v2')
    
    def get_domain(self) -> str:
        """Get the domain part of WordPress URL for internal links"""
        try:
            parsed = urlparse(self.base_url)
            return f"{parsed.scheme}://{parsed.netloc}"
        except Exception:
            return self.base_url
    
    def test_connection(self) -> bool:
        """Test WordPress API connection"""
        try:
            response = self.session.get(f"{self.base_url}/posts", params={'per_page': 1})
            return response.status_code == 200
        except Exception as e:
            logger.error(f"WordPress connection test failed: {str(e)}")
            return False
    
    def get_or_create_tag(self, tag_name: str, tag_slug: str) -> Optional[int]:
        """Get existing tag or create new one"""
        try:
            # Search for existing tag
            response = self.session.get(f"{self.base_url}/tags", params={
                'slug': tag_slug,
                'per_page': 1
            })
            
            if response.status_code == 200:
                tags = response.json()
                if tags:
                    return tags[0]['id']
            
            # Create new tag
            tag_data = {
                'name': tag_name,
                'slug': tag_slug
            }
            
            response = self.session.post(f"{self.base_url}/tags", json=tag_data)
            
            if response.status_code == 201:
                return response.json()['id']
            else:
                logger.error(f"Failed to create tag '{tag_name}': {response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"Error handling tag '{tag_name}': {str(e)}")
            return None
    
    def upload_media(self, file_data: bytes, filename: str) -> Optional[int]:
        """Upload media file to WordPress"""
        try:
            # Prepare headers for media upload
            headers = {
                'Authorization': self.session.headers.get('Authorization'),
                'Content-Disposition': f'attachment; filename="{filename}"'
            }
            
            # Determine content type
            content_type = 'image/jpeg'  # Default
            if filename.lower().endswith('.png'):
                content_type = 'image/png'
            elif filename.lower().endswith('.gif'):
                content_type = 'image/gif'
            elif filename.lower().endswith('.webp'):
                content_type = 'image/webp'
            
            headers['Content-Type'] = content_type
            
            response = requests.post(
                f"{self.base_url}/media",
                data=file_data,
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 201:
                media_data = response.json()
                return media_data['id']
            else:
                logger.error(f"Media upload failed: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"Error uploading media: {str(e)}")
            return None
    
    def create_post(self, post_data: Dict[str, Any]) -> Optional[int]:
        """Create a new WordPress post"""
        try:
            logger.info(f"Creating WordPress post: {post_data.get('title', 'No title')}")
            
            # Prepare tag IDs
            tag_ids = []
            if 'tags' in post_data and isinstance(post_data['tags'], list):
                for tag in post_data['tags']:
                    tag_slug = tag.lower().replace(' ', '-')
                    tag_id = self.get_or_create_tag(tag.replace('-', ' ').title(), tag_slug)
                    if tag_id:
                        tag_ids.append(tag_id)
            
            # Prepare post payload
            payload = {
                'title': post_data.get('title', ''),
                'content': post_data.get('content', ''),
                'excerpt': post_data.get('excerpt', ''),
                'status': post_data.get('status', 'draft'),
                'categories': post_data.get('categories', []),
                'tags': tag_ids
            }
            
            # Add featured media if provided
            if post_data.get('featured_media'):
                payload['featured_media'] = post_data['featured_media']
            
            # Try to add Yoast meta data (silently ignore failures)
            meta_data = {}
            
            # Meta description from excerpt
            if post_data.get('excerpt'):
                meta_data['_yoast_wpseo_metadesc'] = post_data['excerpt'][:160]
            
            # Focus keyword from title (first 2 words)
            title_words = post_data.get('title', '').split()[:2]
            if title_words:
                meta_data['_yoast_wpseo_focuskw'] = ' '.join(title_words).lower()
            
            if meta_data:
                payload['meta'] = meta_data
            
            # Create the post
            response = self.session.post(f"{self.base_url}/posts", json=payload)
            
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
