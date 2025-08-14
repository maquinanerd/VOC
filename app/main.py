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

from . import (
    logging_conf, feeds, extractor, ai_processor, rewriter, tags,
    categorizer, media, wordpress, store, cleanup, keys
)
from .config import (
    PIPELINE_ORDER, RSS_FEEDS, USER_AGENT, WORDPRESS_CONFIG,
    WORDPRESS_CATEGORIES, SCHEDULE_CONFIG, PIPELINE_CONFIG, AI_CONFIG
)

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

        self.ai_processor = ai_processor.AIProcessor()
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

            # Process with AI using category-based key management
            rewritten_content = self.ai_processor.rewrite_content(
                title=article_data['title'],
                excerpt=article_data.get('excerpt', ''),
                content=article_data['content'],
                tags_text=tags_text,
                category=feed_category,
                publisher_name=PIPELINE_CONFIG['publisher_name']
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
                    # Check if article has been processed (published) before
                    if not self.db.is_article_processed(source_id, item['id']):
                        new_items.append(item)
                
                # Limit articles per feed per cycle
                max_articles = SCHEDULE_CONFIG.get('max_articles_per_feed', 3)
                new_items = new_items[:max_articles]
                
                logger.info(f"Found {len(new_items)} new articles for {source_id}")
                
                # Process each article
                for item in new_items:
                    success = self.process_single_article(source_id, item)
                    if success:
                        total_processed += 1
                    
                    # Delay between AI calls
                    if len(new_items) > 1 and item != new_items[-1]:
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
    # The check is for any list of keys in the AI_CONFIG dictionary values being non-empty.
    ai_keys_available = any(keys for keys in AI_CONFIG.values())
    
    if not ai_keys_available:
        logger.critical("No AI API keys available in any category. Check your .env file for GEMINI_* keys.")
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
