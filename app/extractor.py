"""
Content extraction module using trafilatura with BeautifulSoup fallback
"""

import logging
import re
from typing import Dict, Any, List, Optional
from urllib.parse import urljoin, urlparse

import requests
import trafilatura
from readability import Document
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class ContentExtractor:
    """Extract complete article content from web pages"""
    
    def __init__(self, user_agent: str):
        self.user_agent = user_agent
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
        })
    
    def download_html(self, url: str) -> tuple[Optional[str], Optional[str]]:
        """Download HTML content from URL with redirects"""
        try:
            response = self.session.get(url, timeout=15, allow_redirects=True)
            response.raise_for_status()
            
            # Update final URL after redirects
            final_url = response.url
            logger.debug(f"Final URL after redirects: {final_url}")
            
            return response.text, final_url
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Error downloading {url}: {str(e)}")
            return None, None
    
    def extract_with_trafilatura(self, html: str, url: str) -> Optional[Dict[str, Any]]:
        """Extract content using trafilatura"""
        try:
            # Configure trafilatura options
            extracted = trafilatura.extract(
                html,
                include_images=True,
                include_links=True,
                include_formatting=True,
                output_format='html'
            )
            
            if not extracted:
                return None
            
            # Also extract metadata
            metadata = trafilatura.extract_metadata(html)
            
            title = metadata.title if metadata else ""
            excerpt = metadata.description if metadata else ""
            
            return {
                'title': title or "",
                'excerpt': excerpt or "",
                'content': extracted,
                'method': 'trafilatura'
            }
            
        except Exception as e:
            logger.error(f"Trafilatura extraction failed for {url}: {str(e)}")
            return None
    
    def extract_with_readability(self, html: str, url: str) -> Optional[Dict[str, Any]]:
        """Extract content using readability-lxml"""
        try:
            doc = Document(html)
            content = doc.summary()
            title = doc.title()
            
            if not content:
                return None
            
            return {
                'title': title or "",
                'excerpt': "",  # Readability doesn't extract excerpts
                'content': content,
                'method': 'readability'
            }
            
        except Exception as e:
            logger.error(f"Readability extraction failed for {url}: {str(e)}")
            return None
    
    def extract_with_beautifulsoup(self, html: str, url: str) -> Optional[Dict[str, Any]]:
        """Fallback extraction using BeautifulSoup"""
        try:
            soup = BeautifulSoup(html, 'html.parser')
            
            # Extract title
            title_tag = soup.find('title') or soup.find('h1')
            title = title_tag.get_text().strip() if title_tag else ""
            
            # Extract description
            meta_desc = soup.find('meta', attrs={'name': 'description'}) or \
                       soup.find('meta', attrs={'property': 'og:description'})
            excerpt = ""
            if meta_desc and hasattr(meta_desc, 'get'):
                content = meta_desc.get('content')
                if content:
                    excerpt = str(content).strip()
            
            # Try to find main content area
            content_selectors = [
                'article', '[class*="content"]', '[class*="post"]', 
                '[class*="entry"]', '[id*="content"]', 'main'
            ]
            
            content_element = None
            for selector in content_selectors:
                content_element = soup.select_one(selector)
                if content_element:
                    break
            
            if not content_element:
                content_element = soup.find('body')
            
            if not content_element:
                return None
            
            # Remove unwanted elements
            if hasattr(content_element, 'find_all'):
                for unwanted in content_element.find_all(['script', 'style', 'nav', 'header', 'footer']):
                    if hasattr(unwanted, 'decompose'):
                        unwanted.decompose()
            
            content = str(content_element)
            
            return {
                'title': title,
                'excerpt': excerpt,
                'content': content,
                'method': 'beautifulsoup'
            }
            
        except Exception as e:
            logger.error(f"BeautifulSoup extraction failed for {url}: {str(e)}")
            return None
    
    def extract_images(self, soup: BeautifulSoup, base_url: str) -> List[Dict[str, str]]:
        """Extract images from content"""
        images = []
        
        for img in soup.find_all('img'):
            if hasattr(img, 'get'):
                src = img.get('src')
                if not src:
                    continue
                
                # Convert relative URLs to absolute
                src = urljoin(base_url, str(src))
                
                # Skip tiny images (likely icons/ads)
                width = img.get('width')
                height = img.get('height')
                if width and height:
                    try:
                        if int(str(width)) < 100 or int(str(height)) < 100:
                            continue
                    except ValueError:
                        pass
                
                alt_text = img.get('alt', '')
                if alt_text:
                    alt_text = str(alt_text).strip()
                else:
                    alt_text = ''
                    
                images.append({
                    'src': src,
                    'alt': alt_text
                })
        
        return images
    
    def extract_videos(self, soup: BeautifulSoup) -> List[Dict[str, str]]:
        """Extract YouTube videos and other embeds"""
        videos = []
        
        # Find YouTube iframes
        for iframe in soup.find_all('iframe'):
            if hasattr(iframe, 'get'):
                src = iframe.get('src', '')
                src_str = str(src) if src else ''
                if 'youtube.com' in src_str or 'youtu.be' in src_str:
                    videos.append({
                        'type': 'youtube',
                        'src': src_str,
                        'html': str(iframe)
                    })
        
        # Find YouTube embed divs/objects
        for embed in soup.find_all(['embed', 'object']):
            if hasattr(embed, 'get'):
                src1 = embed.get('src', '')
                src2 = embed.get('data', '')
                src = str(src1) if src1 else str(src2) if src2 else ''
                if 'youtube.com' in src or 'youtu.be' in src:
                    videos.append({
                        'type': 'youtube',
                        'src': src,
                        'html': str(embed)
                    })
        
        return videos
    
    def extract_main_image(self, soup: BeautifulSoup, base_url: str) -> Optional[str]:
        """Extract the main image (og:image or first content image)"""
        # Try og:image first
        og_image = soup.find('meta', attrs={'property': 'og:image'})
        if og_image and hasattr(og_image, 'get'):
            src = og_image.get('content')
            if src:
                return urljoin(base_url, str(src))
        
        # Try twitter:image
        twitter_image = soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and hasattr(twitter_image, 'get'):
            src = twitter_image.get('content')
            if src:
                return urljoin(base_url, str(src))
        
        # Find first substantial image in content
        images = self.extract_images(soup, base_url)
        if images:
            return images[0]['src']
        
        return None
    
    def extract_content(self, url: str) -> Optional[Dict[str, Any]]:
        """Extract complete article content using multiple methods"""
        logger.info(f"Extracting content from: {url}")
        
        # Download HTML
        download_result = self.download_html(url)
        if not download_result or download_result[0] is None:
            return None
        
        html, final_url = download_result
        
        # Try trafilatura first
        result = self.extract_with_trafilatura(html, final_url)
        
        # Fallback to readability
        if not result:
            result = self.extract_with_readability(html, final_url)
        
        # Final fallback to BeautifulSoup
        if not result:
            result = self.extract_with_beautifulsoup(html, final_url)
        
        if not result:
            logger.error(f"All extraction methods failed for {url}")
            return None
        
        # Parse content with BeautifulSoup for additional extraction
        soup = BeautifulSoup(result['content'], 'html.parser')
        
        # Extract additional elements
        images = self.extract_images(soup, final_url)
        videos = self.extract_videos(soup)
        main_image = self.extract_main_image(BeautifulSoup(html, 'html.parser'), final_url)
        
        # Clean up title (remove HTML tags if any)
        title = re.sub(r'<[^>]+>', '', result['title']).strip()
        
        final_result = {
            'title': title,
            'excerpt': result['excerpt'],
            'content': result['content'],
            'images': images,
            'videos': videos,
            'main_image': main_image,
            'url': final_url,
            'extraction_method': result['method']
        }
        
        logger.info(f"Successfully extracted content using {result['method']}")
        logger.debug(f"Extracted {len(images)} images, {len(videos)} videos")
        
        return final_result
