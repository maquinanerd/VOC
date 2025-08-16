import logging
import time
from typing import Dict, Any

from .config import (
    PIPELINE_ORDER,
    RSS_FEEDS,
    SCHEDULE_CONFIG,
    WORDPRESS_CONFIG,
    WORDPRESS_CATEGORIES,
    PIPELINE_CONFIG,
)
from .store import Database
from .feeds import FeedReader
from .extractor import ContentExtractor
from .tags import TagExtractor
from .ai_processor import AIProcessor
from .rewriter import ContentRewriter
from .categorizer import Categorizer
from .wordpress import WordPressClient

logger = logging.getLogger(__name__)


def run_pipeline_cycle():
    """Executes a full cycle of the content processing pipeline."""
    logger.info("Starting new pipeline cycle.")

    db = Database()
    feed_reader = FeedReader(user_agent=PIPELINE_CONFIG.get('publisher_name', 'Bot'))
    extractor = ContentExtractor(user_agent=PIPELINE_CONFIG.get('publisher_name', 'Bot'))
    tag_extractor = TagExtractor()
    ai_processor = AIProcessor()
    rewriter = ContentRewriter()
    categorizer = Categorizer()
    wp_client = WordPressClient(config=WORDPRESS_CONFIG, categories_map=WORDPRESS_CATEGORIES)

    processed_articles_in_cycle = 0

    try:
        for source_id in PIPELINE_ORDER:
            feed_config = RSS_FEEDS.get(source_id)
            if not feed_config:
                logger.warning(f"No configuration found for feed source: {source_id}")
                continue

            logger.info(f"Processing feed: {source_id}")
            try:
                feed_items = feed_reader.read_feeds(feed_config['urls'], source_id)
                new_articles = db.filter_new_articles(source_id, feed_items)

                if not new_articles:
                    logger.info(f"No new articles found for {source_id}.")
                    continue

                logger.info(f"Found {len(new_articles)} new articles for {source_id}")

                for article_data in new_articles[:SCHEDULE_CONFIG.get('max_articles_per_feed', 3)]:
                    try:
                        logger.info(f"Processing article: {article_data['title']} from {source_id}")
                        db.update_article_status(article_data['id'], 'PROCESSING')

                        extracted_content = extractor.extract_content(article_data['link'])
                        if not extracted_content or not extracted_content.get('content'):
                            logger.warning(f"Failed to extract content from {article_data['link']}")
                            db.update_article_status(article_data['id'], 'FAILED', reason="Extraction failed")
                            continue

                        tags = tag_extractor.extract_tags(extracted_content['content'], extracted_content['title'])

                        rewritten_text = ai_processor.rewrite_content(
                            category=feed_config['category'],
                            title=extracted_content['title'],
                            excerpt=extracted_content.get('excerpt', ''),
                            content=extracted_content['content'],
                            tags_text=', '.join(tags),
                            domain=wp_client.get_domain(),
                            publisher_name=PIPELINE_CONFIG['publisher_name']
                        )

                        if not rewritten_text:
                            logger.warning(f"AI processing failed for {article_data['link']}")
                            db.update_article_status(article_data['id'], 'FAILED', reason="AI processing failed")
                            continue

                        processed_content = rewriter.process_content(rewritten_text, tags, wp_client.get_domain())

                        wp_category_id = categorizer.map_category(source_id, WORDPRESS_CATEGORIES)

                        post_payload = {
                            'title': processed_content['title'],
                            'content': processed_content['content'],
                            'excerpt': processed_content['excerpt'],
                            'status': 'publish',
                            'categories': [wp_category_id] if wp_category_id else [],
                            'tags': tags,
                            'featured_media_url': extracted_content.get('main_image')
                        }

                        wp_post_id = wp_client.create_post(post_payload)

                        if wp_post_id:
                            db.save_processed_post(article_data['id'], wp_post_id)
                            logger.info(f"Successfully published post {wp_post_id} for article {article_data['id']}")
                            processed_articles_in_cycle += 1
                        else:
                            logger.error(f"Failed to publish post for {article_data['link']}")
                            db.update_article_status(article_data['id'], 'FAILED', reason="WordPress publishing failed")

                        time.sleep(SCHEDULE_CONFIG['api_call_delay_seconds'])

                    except Exception as e:
                        logger.error(f"Error processing article {article_data.get('link', 'N/A')}: {e}", exc_info=True)
                        db.update_article_status(article_data['id'], 'FAILED', reason=str(e))

            except Exception as e:
                logger.error(f"Error processing feed {source_id}: {e}", exc_info=True)

    finally:
        logger.info(f"Pipeline cycle completed. Processed {processed_articles_in_cycle} articles.")
        db.close()
        wp_client.close()