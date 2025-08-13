"""
Content rewriting and validation module
"""

import logging
import re
from typing import Dict, List, Any, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class ContentRewriter:
    """Content rewriter and HTML validator"""
    
    def __init__(self):
        self.allowed_tags = {'p', 'b', 'a', 'figure', 'img', 'iframe'}
        self.allowed_attrs = {
            'a': ['href'],
            'img': ['src', 'alt', 'width', 'height'],
            'iframe': ['src', 'width', 'height', 'frameborder', 'allowfullscreen']
        }
    
    def validate_title(self, title: str) -> str:
        """Ensure title is plain text without HTML"""
        if not title:
            return ""
        
        # Remove any HTML tags
        clean_title = re.sub(r'<[^>]+>', '', title).strip()
        
        # Decode HTML entities
        clean_title = BeautifulSoup(clean_title, 'html.parser').get_text()
        
        return clean_title
    
    def validate_excerpt(self, excerpt: str) -> str:
        """Validate and clean excerpt"""
        if not excerpt:
            return ""
        
        # Remove HTML tags from excerpt
        clean_excerpt = re.sub(r'<[^>]+>', '', excerpt).strip()
        
        # Decode HTML entities
        clean_excerpt = BeautifulSoup(clean_excerpt, 'html.parser').get_text()
        
        # Limit length (WordPress excerpts are typically short)
        if len(clean_excerpt) > 300:
            clean_excerpt = clean_excerpt[:297] + "..."
        
        return clean_excerpt
    
    def sanitize_html(self, content: str) -> str:
        """Sanitize HTML content keeping only allowed tags and attributes"""
        soup = BeautifulSoup(content, 'html.parser')
        
        # Remove all tags not in allowed list
        for tag in soup.find_all(True):
            if hasattr(tag, 'name') and tag.name not in self.allowed_tags:
                # Keep the text content but remove the tag
                if hasattr(tag, 'unwrap'):
                    tag.unwrap()
            elif hasattr(tag, 'name') and hasattr(tag, 'attrs'):
                # Remove attributes not in allowed list
                allowed = self.allowed_attrs.get(tag.name, [])
                attrs_to_remove = [attr for attr in tag.attrs if attr not in allowed]
                for attr in attrs_to_remove:
                    if attr in tag.attrs:
                        del tag.attrs[attr]
        
        return str(soup)
    
    def wrap_paragraphs(self, content: str) -> str:
        """Ensure all text content is wrapped in <p> tags"""
        soup = BeautifulSoup(content, 'html.parser')
        
        # Find all text nodes that aren't already in allowed container tags
        container_tags = {'p', 'figure', 'iframe'}
        
        new_soup = BeautifulSoup('', 'html.parser')
        current_p = None
        
        for element in soup.contents:
            if isinstance(element, str):
                # Text node
                text = element.strip()
                if text:
                    if current_p is None:
                        current_p = new_soup.new_tag('p')
                        new_soup.append(current_p)
                    current_p.append(text)
            else:
                # Tag element
                if hasattr(element, 'name') and element.name in container_tags:
                    current_p = None
                    new_soup.append(element)
                else:
                    # Unwrap non-container tags but keep content
                    if current_p is None:
                        current_p = new_soup.new_tag('p')
                        new_soup.append(current_p)
                    current_p.append(element)
        
        return str(new_soup)
    
    def insert_internal_links(self, content: str, domain: str, tags: List[str]) -> str:
        """Insert internal links based on extracted tags"""
        if not domain or not tags:
            return content
        
        soup = BeautifulSoup(content, 'html.parser')
        
        # Create tag patterns for matching
        tag_patterns = []
        for tag in tags:
            # Create variations of the tag for matching
            variations = [
                tag.replace('-', ' '),  # "star-wars" -> "Star Wars"
                tag.replace('-', ''),   # "star-wars" -> "StarWars"
                tag
            ]
            for variation in variations:
                if len(variation) > 3:  # Skip very short tags
                    tag_patterns.append({
                        'pattern': re.compile(r'\b' + re.escape(variation) + r'\b', re.IGNORECASE),
                        'tag': tag,
                        'text': variation
                    })
        
        # Process text in paragraphs
        for p_tag in soup.find_all('p'):
            text = p_tag.get_text()
            
            # Track already processed positions to avoid overlapping links
            processed_ranges = []
            
            for tag_info in tag_patterns:
                matches = list(tag_info['pattern'].finditer(text))
                
                for match in matches:
                    start, end = match.span()
                    
                    # Check if this range overlaps with already processed ranges
                    overlap = any(
                        (start < r_end and end > r_start) 
                        for r_start, r_end in processed_ranges
                    )
                    
                    if not overlap:
                        # Replace text with link
                        original_text = match.group()
                        link_url = f"{domain}/tag/{tag_info['tag']}"
                        
                        # Create link element
                        new_link = soup.new_tag('a', href=link_url)
                        
                        # Decide whether to add bold formatting
                        if self._should_bold_tag(tag_info['tag']):
                            bold_tag = soup.new_tag('b')
                            bold_tag.string = original_text
                            new_link.append(bold_tag)
                        else:
                            new_link.string = original_text
                        
                        # Replace in the paragraph
                        p_text = p_tag.get_text()
                        before = p_text[:start]
                        after = p_text[end:]
                        
                        # Clear and rebuild paragraph
                        if hasattr(p_tag, 'clear') and hasattr(p_tag, 'append'):
                            p_tag.clear()
                            if before:
                                p_tag.append(before)
                            p_tag.append(new_link)
                            if after:
                                p_tag.append(after)
                        
                        processed_ranges.append((start, end))
                        break  # Only process first match per paragraph
        
        return str(soup)
    
    def _should_bold_tag(self, tag: str) -> bool:
        """Determine if a tag should be bolded when linked"""
        # Bold tags for movies, shows, games, and character names
        bold_indicators = [
            'movie', 'film', 'show', 'series', 'game', 'season',
            'marvel', 'dc', 'disney', 'netflix', 'hbo', 'amazon'
        ]
        
        tag_lower = tag.lower()
        return any(indicator in tag_lower for indicator in bold_indicators)
    
    def add_bold_formatting(self, content: str) -> str:
        """Add bold formatting to relevant terms"""
        soup = BeautifulSoup(content, 'html.parser')
        
        # Terms that should be bolded (case insensitive)
        bold_patterns = [
            r'\b[A-Z][a-z]+ \d{4}\b',  # Years like "March 2024"
            r'\b(Netflix|Disney\+|HBO|Amazon Prime|Marvel|DC)\b',  # Platforms and studios
            r'\b(Season \d+|Episode \d+)\b',  # Season/Episode numbers
        ]
        
        for p_tag in soup.find_all('p'):
            text = str(p_tag)
            
            for pattern in bold_patterns:
                text = re.sub(
                    pattern, 
                    lambda m: f'<b>{m.group()}</b>', 
                    text, 
                    flags=re.IGNORECASE
                )
            
            # Replace paragraph content
            new_p = BeautifulSoup(text, 'html.parser')
            p_tag.replace_with(new_p)
        
        return str(soup)
    
    def preserve_media(self, content: str, images: List[Dict[str, str]], videos: List[Dict[str, str]]) -> str:
        """Ensure all original media is preserved in the content"""
        soup = BeautifulSoup(content, 'html.parser')
        
        # Add missing images
        existing_images = {img.get('src') for img in soup.find_all('img')}
        
        for image in images:
            if image['src'] not in existing_images:
                # Create image element
                img_tag = soup.new_tag('img', src=image['src'])
                if image.get('alt'):
                    img_tag['alt'] = image['alt']
                
                # Wrap in figure if it's a substantial image
                if 'content' in image.get('alt', '').lower() or len(image.get('alt', '')) > 20:
                    figure = soup.new_tag('figure')
                    figure.append(img_tag)
                    soup.append(figure)
                else:
                    soup.append(img_tag)
        
        # Add missing videos
        existing_videos = {iframe.get('src') for iframe in soup.find_all('iframe')}
        
        for video in videos:
            if video['src'] not in existing_videos:
                # Parse the video HTML
                video_soup = BeautifulSoup(video['html'], 'html.parser')
                video_element = video_soup.find(['iframe', 'embed', 'object'])
                
                if video_element:
                    soup.append(video_element)
        
        return str(soup)
    
    def process_content(self, ai_content: Dict[str, str], images: List[Dict[str, str]], 
                       videos: List[Dict[str, str]], domain: str, tags: List[str]) -> Dict[str, str]:
        """Process and validate the complete content from AI"""
        logger.info("Processing and validating rewritten content")
        
        # Validate title (plain text only)
        title = self.validate_title(ai_content.get('title', ''))
        
        # Validate excerpt
        excerpt = self.validate_excerpt(ai_content.get('excerpt', ''))
        
        # Process content
        content = ai_content.get('content', '')
        
        # Sanitize HTML
        content = self.sanitize_html(content)
        
        # Wrap content in paragraphs
        content = self.wrap_paragraphs(content)
        
        # Preserve original media
        content = self.preserve_media(content, images, videos)
        
        # Add internal links
        content = self.insert_internal_links(content, domain, tags)
        
        # Add bold formatting
        content = self.add_bold_formatting(content)
        
        # Final sanitization pass
        content = self.sanitize_html(content)
        
        result = {
            'title': title,
            'excerpt': excerpt,
            'content': content
        }
        
        logger.info("Content processing completed successfully")
        return result
