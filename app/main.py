#!/usr/bin/env python3
"""
Main application entry point with scheduler and pipeline management
"""

import argparse
import logging
import os
import signal
import sys
import time
from typing import List, Dict, Any

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

from . import logging_conf
from . import feeds
from . import extractor
from . import ai_processor
from . import rewriter
from . import tags
from . import categorizer
from . import media
from . import wordpress
from . import store
from . import cleanup

# Configuration constants
PIPELINE_ORDER = [
    'screenrant_movies', 'screenrant_tv',
    'movieweb_movies',
    'collider_movies', 'collider_tv',
    'cbr_movies', 'cbr_tv',
    'gamerant_games', 'thegamer_games',
]

RSS_FEEDS = {
    'screenrant_movies': {
        'urls': ['https://screenrant.com/feed/movie-news/'], 
        'category': 'movies',
        'primary_key': 'GEMINI_MOVIES_1'
    },
    'movieweb_movies': {
        'urls': ['https://movieweb.com/feed/'], 
        'category': 'movies',
        'primary_key': 'GEMINI_MOVIES_2'
    },
    'collider_movies': {
        'urls': ['https://collider.com/feed/category/movie-news/'], 
        'category': 'movies',
        'primary_key': 'GEMINI_MOVIES_3'
    },
    'cbr_movies': {
        'urls': ['https://www.cbr.com/feed/category/movies/news-movies/'], 
        'category': 'movies',
        'primary_key': 'GEMINI_MOVIES_4'
    },
    'screenrant_tv': {
        'urls': ['https://screenrant.com/feed/tv-news/'], 
        'category': 'series',
        'primary_key': 'GEMINI_SERIES_1'
    },
    'collider_tv': {
        'urls': ['https://collider.com/feed/category/tv-news/'], 
        'category': 'series',
        'primary_key': 'GEMINI_SERIES_2'
    },
    'cbr_tv': {
        'urls': ['https://www.cbr.com/feed/category/tv/news-tv/'], 
        'category': 'series',
        'primary_key': 'GEMINI_SERIES_3'
    },
    'gamerant_games': {
        'urls': ['https://gamerant.com/feed/gaming/'], 
        'category': 'games',
        'primary_key': 'GEMINI_GAMES_1'
    },
    'thegamer_games': {
        'urls': ['https://www.thegamer.com/feed/category/game-news/'], 
        'category': 'games',
        'primary_key': 'GEMINI_GAMES_2'
    }
}

USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'

AI_CONFIG = {
    'movies': {
        'backup_keys': [os.getenv('GEMINI_BACKUP_1'), os.getenv('GEMINI_BACKUP_2')]
    },
    'series': {
        'backup_keys': [os.getenv('GEMINI_BACKUP_3'), os.getenv('GEMINI_BACKUP_4')]
    },
    'games': {
        'backup_keys': [os.getenv('GEMINI_BACKUP_5')]
    }
}

WORDPRESS_CONFIG = {
    'url': os.getenv('WORDPRESS_URL'),      # ex: https://maquinanerd.com.br/wp-json/wp/v2/
    'user': os.getenv('WORDPRESS_USER'),
    'password': os.getenv('WORDPRESS_PASSWORD')
}

WORDPRESS_CATEGORIES = {
    'Notícias': 20, 'Filmes': 24, 'Séries': 21, 'Games': 73,
}

SCHEDULE_CONFIG = {
    'check_interval': 15,          # minutos
    'max_articles_per_feed': 3,    # por ciclo - ATIVO: 3 posts por feed
    'api_call_delay': 30,          # segundos entre chamadas à IA
    'cleanup_after_hours': 12
}

PIPELINE_CONFIG = {
    'images_mode': os.getenv('IMAGES_MODE', 'hotlink'),  # 'hotlink' | 'download_upload'
    'attribution_policy': 'Via {domain}',
    'publisher_name': 'Máquina Nerd',
    'publisher_logo_url': 'https://www.maquinanerd.com.br/wp-content/uploads/2023/11/logo-maquina-nerd-400px.png'
}

logger = logging.getLogger(__name__)


class PipelineManager:
    """Main pipeline manager for RSS processing"""
    
    def __init__(self):
        self.db = store.Database()
        # Filter None values from config
        filtered_wp_config = {k: v for k, v in WORDPRESS_CONFIG.items() if v is not None}
        self.wp_client = wordpress.WordPressClient(filtered_wp_config, WORDPRESS_CATEGORIES)
        self.feed_reader = feeds.FeedReader(USER_AGENT)
        self.content_extractor = extractor.ContentExtractor(USER_AGENT)
        # Filter None values from AI config
        filtered_ai_config = {}
        for category, keys in AI_CONFIG.items():
            filtered_ai_config[category] = [k for k in keys if k is not None]
        self.ai_processor = ai_processor.AIProcessor(filtered_ai_config)
        self.content_rewriter = rewriter.ContentRewriter()
        self.tag_extractor = tags.TagExtractor()
        self.categorizer = categorizer.Categorizer()
        self.media_handler = media.MediaHandler(PIPELINE_CONFIG, self.wp_client)
        
    def process_single_article(self, source_id: str, item: Dict[str, Any]) -> bool:
        """Process a single article through the complete pipeline"""
        try:
            logger.info(f"Processing article: {item.get('title', 'No title')} from {source_id}")
            
            # Extract full content
            article_data = self.content_extractor.extract_content(item['link'])
            if not article_data:
                logger.warning(f"Failed to extract content from {item['link']}")
                return False
                
            # Extract tags
            article_tags = self.tag_extractor.extract_tags(
                article_data['content'], 
                article_data['title']
            )
            tags_text = ', '.join(article_tags)
            
            # Get category and primary key for AI processing
            feed_config = RSS_FEEDS[source_id]
            feed_category = feed_config['category']
            primary_key = feed_config['primary_key']
            
            # Process with AI using feed-specific key
            rewritten_content = self.ai_processor.rewrite_content(
                title=article_data['title'],
                excerpt=article_data.get('excerpt', ''),
                content=article_data['content'],
                tags_text=tags_text,
                category=feed_category,
                primary_key=primary_key
            )
            
            if not rewritten_content:
                logger.warning(f"AI processing failed for {item['link']}")
                return False
                
            # Rewrite and validate content
            final_content = self.content_rewriter.process_content(
                rewritten_content,
                article_data.get('images', []),
                article_data.get('videos', []),
                self.wp_client.get_domain(),
                article_tags
            )
            
            # Handle media
            featured_media_id = None
            if article_data.get('main_image'):
                featured_media_id = self.media_handler.handle_main_image(
                    article_data['main_image']
                )
            
            # Map category
            wp_category_id = self.categorizer.map_category(source_id, WORDPRESS_CATEGORIES)
            
            # Publish to WordPress
            post_data = {
                'title': final_content['title'],
                'content': final_content['content'],
                'excerpt': final_content['excerpt'],
                'categories': [wp_category_id],
                'tags': article_tags,
                'featured_media': featured_media_id,
                'status': 'publish'
            }
            
            wp_post_id = self.wp_client.create_post(post_data)
            if wp_post_id:
                # Save to database
                self.db.save_processed_post(
                    source_id=source_id,
                    external_id=item['id'],
                    wp_post_id=wp_post_id
                )
                logger.info(f"Successfully published post {wp_post_id}")
                return True
            else:
                logger.error(f"Failed to publish post for {item['link']}")
                return False
                
        except Exception as e:
            logger.error(f"Error processing article {item.get('link', 'Unknown')}: {str(e)}")
            return False
    
    def run_pipeline_cycle(self) -> None:
        """Run a complete pipeline cycle through all feeds"""
        logger.info("Starting pipeline cycle")
        
        total_processed = 0
        for source_id in PIPELINE_ORDER:
            try:
                if source_id not in RSS_FEEDS:
                    logger.warning(f"Source {source_id} not found in RSS_FEEDS")
                    continue
                    
                feed_config = RSS_FEEDS[source_id]
                logger.info(f"Processing feed: {source_id}")
                
                # Read RSS feed
                items = self.feed_reader.read_feeds(feed_config['urls'], source_id)
                
                # Filter new items
                new_items = []
                for item in items:
                    if not self.db.is_article_seen(source_id, item['id']):
                        new_items.append(item)
                        self.db.mark_article_seen(source_id, item['id'])
                
                # Limit articles per feed per cycle
                max_articles = SCHEDULE_CONFIG['max_articles_per_feed']
                new_items = new_items[:max_articles]
                
                logger.info(f"Found {len(new_items)} new articles for {source_id}")
                
                # Process each article
                for item in new_items:
                    success = self.process_single_article(source_id, item)
                    if success:
                        total_processed += 1
                    
                    # Delay between AI calls
                    if len(new_items) > 1:  # Don't delay after the last item
                        time.sleep(SCHEDULE_CONFIG['api_call_delay'])
                        
            except Exception as e:
                logger.error(f"Error processing feed {source_id}: {str(e)}")
                continue
        
        logger.info(f"Pipeline cycle completed. Processed {total_processed} articles")


def run_single_cycle():
    """Run a single pipeline cycle (for --once mode)"""
    pipeline = PipelineManager()
    pipeline.run_pipeline_cycle()


def run_cleanup():
    """Run cleanup tasks"""
    cleanup_manager = cleanup.CleanupManager(SCHEDULE_CONFIG['cleanup_after_hours'])
    cleanup_manager.run_cleanup()


def main():
    """Main application entry point"""
    parser = argparse.ArgumentParser(description='RSS to WordPress Automation System')
    parser.add_argument('--once', action='store_true', help='Run a single cycle and exit')
    parser.add_argument('--cleanup', action='store_true', help='Run cleanup and exit')
    
    args = parser.parse_args()
    
    # Initialize logging
    logging_conf.setup_logging()
    
    # Validate critical environment variables
    critical_vars = ['WORDPRESS_URL', 'WORDPRESS_USER', 'WORDPRESS_PASSWORD']
    missing_vars = [var for var in critical_vars if not os.getenv(var)]
    if missing_vars:
        logger.critical(f"Missing critical environment variables: {missing_vars}")
        sys.exit(1)
    
    # Check AI keys
    ai_keys_available = False
    for category, keys in AI_CONFIG.items():
        if any(key for key in keys if key):
            ai_keys_available = True
            break
    
    if not ai_keys_available:
        logger.critical("No AI API keys available in any category")
        sys.exit(1)
    
    # Initialize database
    db = store.Database()
    db.initialize()
    
    if args.cleanup:
        logger.info("Running cleanup tasks")
        run_cleanup()
        return
    
    if args.once:
        logger.info("Running single pipeline cycle")
        run_single_cycle()
        return
    
    # Set up scheduler
    scheduler = BlockingScheduler()
    
    # Add pipeline job
    scheduler.add_job(
        run_single_cycle,
        IntervalTrigger(minutes=SCHEDULE_CONFIG['check_interval']),
        id='pipeline_cycle',
        name='RSS Pipeline Cycle'
    )
    
    # Add cleanup job
    scheduler.add_job(
        run_cleanup,
        IntervalTrigger(hours=SCHEDULE_CONFIG['cleanup_after_hours']),
        id='cleanup_task',
        name='Cleanup Task'
    )
    
    # Handle graceful shutdown
    def signal_handler(signum, frame):
        logger.info("Received shutdown signal, stopping scheduler...")
        scheduler.shutdown()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    logger.info("Starting RSS to WordPress automation system")
    logger.info(f"Pipeline will run every {SCHEDULE_CONFIG['check_interval']} minutes")
    logger.info(f"Cleanup will run every {SCHEDULE_CONFIG['cleanup_after_hours']} hours")
    
    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received, shutting down...")
    except Exception as e:
        logger.critical(f"Critical error in scheduler: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
