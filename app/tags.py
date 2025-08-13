"""
Tag extraction module using heuristics and content analysis
"""

import logging
import re
from typing import List, Set
from slugify import slugify

logger = logging.getLogger(__name__)


class TagExtractor:
    """Extract relevant tags from article content"""
    
    def __init__(self):
        # Common entertainment industry terms
        self.franchise_keywords = {
            # Movies/Series
            'marvel', 'dc', 'disney', 'pixar', 'star wars', 'star trek', 'lord of the rings',
            'harry potter', 'fast and furious', 'transformers', 'x-men', 'avengers',
            'batman', 'superman', 'spider-man', 'iron man', 'wonder woman',
            'netflix', 'hbo', 'amazon prime', 'disney+', 'paramount+', 'apple tv+',
            'stranger things', 'game of thrones', 'house of the dragon', 'the boys',
            'the witcher', 'breaking bad', 'better call saul',
            
            # Gaming
            'playstation', 'xbox', 'nintendo', 'steam', 'epic games', 'ubisoft',
            'activision', 'blizzard', 'ea games', 'rockstar', 'bethesda',
            'call of duty', 'grand theft auto', 'fifa', 'fortnite', 'minecraft',
            'world of warcraft', 'league of legends', 'valorant', 'apex legends',
            'the elder scrolls', 'fallout', 'assassins creed', 'the sims',
            
            # Platforms/Studios
            'warner bros', 'universal', 'sony', 'paramount', 'mgm', '20th century',
            'lucasfilm', 'marvel studios', 'dc films'
        }
        
        # Patterns for recognizing titles and names
        self.title_patterns = [
            r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*(?:\s+\d+)?\b',  # Title Case names
            r'\b(?:The|A|An)\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b',  # Articles with titles
            r'\b[A-Z][a-z]+:\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b',  # Colon titles
        ]
        
        # Common words to exclude
        self.stop_words = {
            'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with',
            'by', 'from', 'as', 'is', 'was', 'are', 'were', 'be', 'been', 'being',
            'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'should',
            'could', 'can', 'may', 'might', 'must', 'shall', 'this', 'that', 'these',
            'those', 'he', 'she', 'it', 'they', 'them', 'their', 'his', 'her', 'its',
            'movie', 'film', 'series', 'show', 'game', 'news', 'report', 'article'
        }
    
    def extract_franchise_tags(self, text: str) -> Set[str]:
        """Extract known franchise and brand names"""
        tags = set()
        text_lower = text.lower()
        
        for keyword in self.franchise_keywords:
            if keyword.lower() in text_lower:
                # Use the original casing for better tag names
                pattern = re.compile(re.escape(keyword), re.IGNORECASE)
                matches = pattern.findall(text)
                if matches:
                    tags.add(slugify(keyword))
        
        return tags
    
    def extract_title_mentions(self, text: str) -> Set[str]:
        """Extract likely titles and proper names from text"""
        tags = set()
        
        for pattern in self.title_patterns:
            matches = re.findall(pattern, text)
            for match in matches:
                # Clean and validate
                cleaned = match.strip()
                if len(cleaned) < 3 or len(cleaned) > 50:
                    continue
                
                # Skip if it's all stop words
                words = cleaned.lower().split()
                if all(word in self.stop_words for word in words):
                    continue
                
                # Skip common non-title phrases
                if any(skip in cleaned.lower() for skip in ['according to', 'reported by', 'said that']):
                    continue
                
                tags.add(slugify(cleaned))
        
        return tags
    
    def extract_quoted_terms(self, text: str) -> Set[str]:
        """Extract terms in quotes (often titles)"""
        tags = set()
        
        # Find quoted strings
        quote_patterns = [
            r'"([^"]{3,50})"',  # Double quotes
            r"'([^']{3,50})'",  # Single quotes
        ]
        
        for pattern in quote_patterns:
            matches = re.findall(pattern, text)
            for match in matches:
                cleaned = match.strip()
                if cleaned and not any(skip in cleaned.lower() for skip in ['said', 'told', 'according']):
                    tags.add(slugify(cleaned))
        
        return tags
    
    def extract_capitalized_terms(self, text: str) -> Set[str]:
        """Extract consistently capitalized terms (likely proper nouns)"""
        tags = set()
        
        # Find terms that appear capitalized multiple times
        words = re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', text)
        word_counts = {}
        
        for word in words:
            if len(word) > 2 and word.lower() not in self.stop_words:
                word_counts[word] = word_counts.get(word, 0) + 1
        
        # Add words that appear multiple times or are known entities
        for word, count in word_counts.items():
            if count > 1 or any(keyword in word.lower() for keyword in self.franchise_keywords):
                tags.add(slugify(word))
        
        return tags
    
    def extract_from_title(self, title: str) -> Set[str]:
        """Extract tags specifically from the article title"""
        tags = set()
        
        # Remove common article prefixes
        clean_title = re.sub(r'^(Watch|See|New|Latest|Breaking|Exclusive):\s*', '', title, flags=re.IGNORECASE)
        
        # Extract main subjects from title
        # Split on common separators
        parts = re.split(r'[:\-–—|]', clean_title)
        
        for part in parts:
            part = part.strip()
            if len(part) > 3:
                # Look for franchise keywords
                for keyword in self.franchise_keywords:
                    if keyword.lower() in part.lower():
                        tags.add(slugify(keyword))
                
                # Extract capitalized terms
                caps = re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', part)
                for cap in caps:
                    if cap.lower() not in self.stop_words and len(cap) > 2:
                        tags.add(slugify(cap))
        
        return tags
    
    def validate_tags(self, tags: Set[str]) -> List[str]:
        """Validate and clean extracted tags"""
        valid_tags = []
        
        for tag in tags:
            # Skip empty or very short tags
            if not tag or len(tag) < 2:
                continue
            
            # Skip numeric-only tags
            if tag.isdigit():
                continue
            
            # Skip very generic tags
            generic_terms = {'new', 'latest', 'news', 'update', 'report', 'first', 'last'}
            if tag in generic_terms:
                continue
            
            # Clean the tag
            clean_tag = slugify(tag)
            if clean_tag and clean_tag not in valid_tags:
                valid_tags.append(clean_tag)
        
        # Limit number of tags
        return sorted(valid_tags)[:15]
    
    def extract_tags(self, content: str, title: str = "") -> List[str]:
        """Extract all relevant tags from content and title"""
        logger.debug("Extracting tags from content")
        
        all_tags = set()
        
        # Combine title and content for processing
        full_text = f"{title} {content}"
        
        # Extract using different methods
        all_tags.update(self.extract_franchise_tags(full_text))
        all_tags.update(self.extract_title_mentions(full_text))
        all_tags.update(self.extract_quoted_terms(full_text))
        all_tags.update(self.extract_capitalized_terms(full_text))
        
        # Special extraction from title
        if title:
            all_tags.update(self.extract_from_title(title))
        
        # Validate and clean tags
        final_tags = self.validate_tags(all_tags)
        
        logger.info(f"Extracted {len(final_tags)} tags: {', '.join(final_tags[:5])}{'...' if len(final_tags) > 5 else ''}")
        
        return final_tags
