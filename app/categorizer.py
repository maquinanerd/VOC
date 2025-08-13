"""
Category mapping module for WordPress categories
"""

import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class Categorizer:
    """Map RSS feeds to WordPress categories"""
    
    def __init__(self):
        # Mapping rules for feed source to content category
        self.feed_category_map = {
            'movies': ['Filmes', 'Notícias'],
            'series': ['Séries', 'Notícias'], 
            'games': ['Games', 'Notícias']
        }
        
        # Default fallback category
        self.default_category = 'Notícias'
    
    def get_feed_type(self, source_id: str) -> str:
        """Determine feed type from source ID"""
        source_lower = source_id.lower()
        
        if '_movies' in source_lower or 'movie' in source_lower:
            return 'movies'
        elif '_tv' in source_lower or 'series' in source_lower:
            return 'series' 
        elif '_games' in source_lower or 'game' in source_lower:
            return 'games'
        else:
            # Fallback based on source name patterns
            if any(keyword in source_lower for keyword in ['film', 'cinema', 'movie']):
                return 'movies'
            elif any(keyword in source_lower for keyword in ['tv', 'television', 'series', 'show']):
                return 'series'
            elif any(keyword in source_lower for keyword in ['game', 'gaming', 'gamer']):
                return 'games'
            
            return 'movies'  # Default fallback
    
    def map_category(self, source_id: str, wordpress_categories: Dict[str, int]) -> int:
        """Map a source ID to WordPress category ID"""
        logger.debug(f"Mapping category for source: {source_id}")
        
        # Get the feed type
        feed_type = self.get_feed_type(source_id)
        
        # Get preferred categories for this feed type
        preferred_categories = self.feed_category_map.get(feed_type, [])
        
        # Try to find the first available category
        for category_name in preferred_categories:
            if category_name in wordpress_categories:
                category_id = wordpress_categories[category_name]
                logger.info(f"Mapped {source_id} to category '{category_name}' (ID: {category_id})")
                return category_id
        
        # Fallback to default category
        if self.default_category in wordpress_categories:
            category_id = wordpress_categories[self.default_category]
            logger.warning(f"Using fallback category '{self.default_category}' for {source_id}")
            return category_id
        
        # Ultimate fallback - use first available category
        if wordpress_categories:
            first_category = list(wordpress_categories.keys())[0]
            category_id = wordpress_categories[first_category]
            logger.warning(f"Using first available category '{first_category}' for {source_id}")
            return category_id
        
        # This should never happen if WordPress is properly configured
        logger.error(f"No categories available for {source_id}")
        return 1  # Default WordPress 'Uncategorized' category
    
    def get_category_for_ai(self, source_id: str) -> str:
        """Get the AI category for content processing"""
        feed_type = self.get_feed_type(source_id)
        
        # Map to AI processing categories
        ai_category_map = {
            'movies': 'movies',
            'series': 'series', 
            'games': 'games'
        }
        
        return ai_category_map.get(feed_type, 'movies')
