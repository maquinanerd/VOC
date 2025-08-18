import logging
import time
import random
from collections import OrderedDict
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
from .ai_processor import AIProcessor
from .categorizer import Categorizer
from .wordpress import WordPressClient
from .html_utils import (
    merge_images_into_content,
    add_credit_to_figures,
    rewrite_img_srcs_with_wp,
    hard_filter_forbidden_html,
)
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


def run_pipeline_cycle():
    """Executes a full cycle of the content processing pipeline."""
    logger.info("Starting new pipeline cycle.")

    db = Database()
    feed_reader = FeedReader(user_agent=PIPELINE_CONFIG.get('publisher_name', 'Bot'))
    extractor = ContentExtractor()
    categorizer = Categorizer()
    wp_client = WordPressClient(config=WORDPRESS_CONFIG, categories_map=WORDPRESS_CATEGORIES)

    processed_articles_in_cycle = 0

    try:
        for i, source_id in enumerate(PIPELINE_ORDER):
            # Check circuit breaker before processing
            consecutive_failures = db.get_consecutive_failures(source_id)
            if consecutive_failures >= 3:
                logger.warning(f"Circuit open for feed {source_id} ({consecutive_failures} fails) → skipping this round.")
                # Reset for the next cycle as per prompt "zere o contador na próxima"
                db.reset_consecutive_failures(source_id)
                continue

            feed_config = RSS_FEEDS.get(source_id)
            if not feed_config:
                logger.warning(f"No configuration found for feed source: {source_id}")
                continue

            category = feed_config['category']
            logger.info(f"Processing feed: {source_id} (Category: {category})")

            ai_processor = AIProcessor(category)

            try:
                feed_items = feed_reader.read_feeds(feed_config['urls'], source_id)
                new_articles = db.filter_new_articles(source_id, feed_items)

                if not new_articles:
                    logger.info(f"No new articles found for {source_id}.")
                    continue

                logger.info(f"Found {len(new_articles)} new articles for {source_id}")

                for article_data in new_articles[:SCHEDULE_CONFIG.get('max_articles_per_feed', 3)]:
                    article_db_id = article_data['db_id']
                    try:
                        logger.info(f"Processing article: {article_data['title']} (DB ID: {article_db_id}) from {source_id}")
                        db.update_article_status(article_db_id, 'PROCESSING')

                        extracted_data = extractor.extract(article_data['link'])
                        if not extracted_data or not extracted_data.get('content'):
                            logger.warning(f"Failed to extract content from {article_data['link']}")
                            db.update_article_status(article_db_id, 'FAILED', reason="Extraction failed")
                            continue

                        # Step 2: Rewrite content with AI
                        rewritten_data, failure_reason = ai_processor.rewrite_content(
                            title=extracted_data['title'],
                            url=article_data['link'],
                            content=extracted_data['content'],
                            domain=wp_client.get_domain(),
                            videos=extracted_data.get('videos', [])
                        )

                        if not rewritten_data:
                            reason = failure_reason or "AI processing failed"
                            # Check for the specific case where the key pool for the category is exhausted
                            if "pool is exhausted" in reason:
                                logger.warning(
                                    f"{feed_config['category']} pool exhausted → marking article FAILED → moving on."
                                )
                            else:
                                logger.warning(f"Article '{article_data['title']}' marked as FAILED (Reason: {reason}). Continuing to next article.")
                            db.update_article_status(article_db_id, 'FAILED', reason=reason)
                            continue

                        # Step 3: Image and HTML processing
                        # 3.1: Ensure images exist in content, injecting if AI removed them
                        content_html = merge_images_into_content(
                            rewritten_data['conteudo_final'],
                            extracted_data.get('images', [])
                        )

                        # 3.2: Upload images to WordPress
                        image_urls_to_upload = []
                        if featured_url := extracted_data.get('featured_image_url'):
                            image_urls_to_upload.append(featured_url)
                        
                        soup = BeautifulSoup(content_html, 'html.parser')
                        for img in soup.find_all('img'):
                            if src := img.get('src'):
                                image_urls_to_upload.append(src)
                        
                        # Deduplicate while preserving order and limit to 8
                        unique_urls = list(OrderedDict.fromkeys(image_urls_to_upload))
                        uploaded_map = {}
                        logger.info(f"Attempting to upload up to 8 images from {len(unique_urls)} unique URLs found.")
                        for img_url in unique_urls[:8]:
                            media_info = wp_client.upload_media_from_url(img_url, rewritten_data['titulo_final'])
                            if media_info and media_info.get('source_url'):
                                uploaded_map[img_url] = media_info['source_url']
                        
                        # 3.3: Rewrite image `src` to point to WordPress
                        content_html = rewrite_img_srcs_with_wp(content_html, uploaded_map)

                        # 3.4: Add credits to figures
                        content_html = add_credit_to_figures(content_html, extracted_data['source_url'])

                        # 3.5: Final sanitization pass
                        content_html = hard_filter_forbidden_html(content_html)

                        # Step 4: Prepare payload for WordPress
                        wp_category_id = categorizer.map_category(source_id, WORDPRESS_CATEGORIES)
                        final_featured_url = extracted_data.get('featured_image_url') or next(iter(uploaded_map.values()), None)
                        
                        post_payload = {
                            'title': rewritten_data['titulo_final'],
                            'content': content_html,
                            'excerpt': rewritten_data['meta_description'],
                            'categories': [wp_category_id] if wp_category_id else [],
                            'tags': rewritten_data.get('tags', []),
                            'featured_image_url': final_featured_url
                        }

                        wp_post_id = wp_client.create_post(post_payload)

                        if wp_post_id:
                            db.save_processed_post(article_db_id, wp_post_id)
                            logger.info(f"Successfully published post {wp_post_id} for article DB ID {article_db_id}")
                            processed_articles_in_cycle += 1
                        else:
                            logger.error(f"Failed to publish post for {article_data['link']}")
                            db.update_article_status(article_db_id, 'FAILED', reason="WordPress publishing failed")

                        # Per-article delay to respect API rate limits and avoid being predictable
                        base_delay = SCHEDULE_CONFIG.get('per_article_delay_seconds', 8)
                        # Add jitter to be less predictable (e.g., for 8s, sleep between 6s and 10s)
                        delay = max(1.0, random.uniform(base_delay - 2, base_delay + 2))
                        logger.info(f"Sleeping for {delay:.1f}s (per-article delay).")
                        time.sleep(delay)

                    except Exception as e:
                        logger.error(f"Error processing article {article_data.get('link', 'N/A')}: {e}", exc_info=True)
                        db.update_article_status(article_db_id, 'FAILED', reason=str(e))

                # If we reach here without a feed-level exception, the processing was successful
                db.reset_consecutive_failures(source_id)

            except Exception as e:
                logger.error(f"Error processing feed {source_id}: {e}", exc_info=True)
                db.increment_consecutive_failures(source_id)

            # Per-feed delay before processing the next source
            if i < len(PIPELINE_ORDER) - 1:
                next_feed = PIPELINE_ORDER[i + 1]
                delay = SCHEDULE_CONFIG.get('per_feed_delay_seconds', 15)
                logger.info(f"Finished feed '{source_id}'. Sleeping for {delay}s before next feed: {next_feed}")
                time.sleep(delay)

    finally:
        logger.info(f"Pipeline cycle completed. Processed {processed_articles_in_cycle} articles.")
        db.close()
        wp_client.close()