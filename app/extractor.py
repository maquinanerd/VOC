import logging
import trafilatura
from bs4 import BeautifulSoup
import requests
from typing import Dict, Optional, Any
from urllib.parse import urljoin, urlparse, parse_qs
import json

from .config import USER_AGENT

logger = logging.getLogger(__name__)

YOUTUBE_DOMAINS = (
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "youtu.be",
    "www.youtu.be",
)


class ContentExtractor:
    """
    Extracts, cleans, and structures web page content for the pipeline.
    """
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': USER_AGENT})

    def _fetch_html(self, url: str) -> Optional[str]:
        """Fetches the raw HTML content of a URL."""
        try:
            response = self.session.get(url, timeout=20.0, allow_redirects=True)
            response.raise_for_status()
            return response.text
        except requests.RequestException as e:
            logger.error(f"Failed to fetch HTML from {url}: {e}")
            return None

    def _pre_clean_html(self, soup: BeautifulSoup):
        """Removes unwanted elements from the soup before content extraction."""
        selectors_to_remove = [
            '[class*="srdb"]',
            '[class*="rating"]',
            '.review',
            '.score',
            '.meter',
        ]
        for selector in selectors_to_remove:
            for element in soup.select(selector):
                element.decompose()
        
        for text_node in soup.find_all(string=lambda t: "powered by srdb" in t.lower()):
            if text_node.find_parent():
                text_node.find_parent().decompose()

        logger.info("Pre-cleaned HTML, removing unwanted widgets and blocks.")

    def _convert_data_img_to_figure(self, soup: BeautifulSoup):
        """Converts divs with 'data-img-url' into <figure> and <img> tags."""
        converted_count = 0
        for div in soup.find_all('div', attrs={'data-img-url': True}):
            img_url = div['data-img-url']
            figure_tag = soup.new_tag('figure')
            img_tag = soup.new_tag('img', src=img_url)
            
            caption_tag = soup.new_tag('figcaption')
            caption_text = div.get_text(strip=True)
            if caption_text:
                caption_tag.string = caption_text
                img_tag['alt'] = caption_text
            
            figure_tag.append(img_tag)
            if caption_text:
                figure_tag.append(caption_tag)

            div.replace_with(figure_tag)
            converted_count += 1
        
        if converted_count > 0:
            logger.info(f"Converted {converted_count} 'data-img-url' divs to <figure> tags.")

    def _extract_featured_image(self, soup: BeautifulSoup, base_url: str) -> Optional[str]:
        """Extracts the main image URL based on a priority list."""
        # 1. Open Graph image
        if og_image := soup.find('meta', property='og:image'):
            if content := og_image.get('content'):
                logger.info("Found featured image via 'og:image'.")
                return urljoin(base_url, content)

        # 2. Twitter image
        if twitter_image := soup.find('meta', attrs={'name': 'twitter:image'}):
            if content := twitter_image.get('content'):
                logger.info("Found featured image via 'twitter:image'.")
                return urljoin(base_url, content)

        # 3. JSON-LD
        for script in soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string)
                if data.get('@type') in ('NewsArticle', 'Article') and 'image' in data:
                    image_info = data['image']
                    if isinstance(image_info, dict) and (url := image_info.get('url')):
                        return urljoin(base_url, url)
                    if isinstance(image_info, list) and image_info:
                        return urljoin(base_url, image_info[0].get('url') or image_info[0])
                    if isinstance(image_info, str):
                        return urljoin(base_url, image_info)
            except (json.JSONDecodeError, TypeError, AttributeError):
                continue

        # 4. First <img> in <article>
        if article_tag := soup.find('article'):
            if first_img := article_tag.find('img'):
                if src := first_img.get('src'):
                    logger.info("Using first <img> in <article> as featured image.")
                    return urljoin(base_url, src)

        logger.warning("Could not find a suitable featured image.")
        return None

    def _extract_youtube_id(self, src: str) -> Optional[str]:
        """Safely extracts a YouTube video ID from a URL."""
        if not src:
            return None
        try:
            u = urlparse(src)
            if u.netloc not in YOUTUBE_DOMAINS:
                return None
            if u.path.startswith("/embed/"):
                return u.path.split("/")[2].split("?")[0]
            if u.path.startswith("/shorts/"):
                return u.path.split("/")[2].split("?")[0]
            if u.netloc.endswith("youtu.be"):
                return u.path.lstrip("/")
            if u.path == "/watch":
                q = parse_qs(u.query)
                return q.get("v", [None])[0]
        except (IndexError, TypeError):
            logger.warning(f"Could not parse YouTube ID from src: {src}")
        return None

    def _extract_youtube_videos(self, soup: BeautifulSoup) -> list[dict]:
        """Extracts all unique YouTube videos from the page content."""
        video_ids = []
        # Direct iframes
        for iframe in soup.find_all("iframe"):
            src = iframe.get("src", "")
            vid = self._extract_youtube_id(src)
            if vid:
                video_ids.append(vid)

        # Common wrappers with ID or data-youtube-id
        for div in soup.select('.w-youtube[id], .youtube[id], [data-youtube-id]'):
            vid = div.get("id") or div.get("data-youtube-id")
            if vid:
                video_ids.append(vid)

        # Deduplicate while preserving order
        seen, ordered_ids = set(), []
        for v_id in video_ids:
            if v_id and v_id not in seen:
                seen.add(v_id)
                ordered_ids.append(v_id)
        
        if ordered_ids:
            logger.info(f"Found {len(ordered_ids)} unique YouTube videos.")

        return [{
            "id": v,
            "embed_url": f"https://www.youtube.com/embed/{v}",
            "watch_url": f"https://www.youtube.com/watch?v={v}"
        } for v in ordered_ids]

    def extract(self, url: str) -> Optional[Dict[str, Any]]:
        """Main extraction method. Fetches, cleans, and extracts content."""
        html = self._fetch_html(url)
        if not html:
            return None

        try:
            soup = BeautifulSoup(html, 'lxml')

            # 1. Pre-clean the HTML to remove unwanted widgets, ads, etc.
            self._pre_clean_html(soup)

            # 2. Convert proprietary image divs to standard <figure> tags
            self._convert_data_img_to_figure(soup)

            # 3. Extract the featured image URL using the priority list
            featured_image_url = self._extract_featured_image(soup, url)

            # 3.5. Extract YouTube videos
            videos = self._extract_youtube_videos(soup)

            # 4. Extract metadata from the cleaned soup before passing to trafilatura
            title = soup.title.string if soup.title else 'No Title Found'
            if og_title := soup.find('meta', property='og:title'):
                if content := og_title.get('content'):
                    title = content

            excerpt = ''
            if meta_desc := soup.find('meta', attrs={'name': 'description'}):
                if content := meta_desc.get('content'):
                    excerpt = content
            elif og_desc := soup.find('meta', property='og:description'):
                if content := og_desc.get('content'):
                    excerpt = content

            # 5. Extract the main content using trafilatura on the cleaned HTML string
            cleaned_html_str = str(soup)
            content_html = trafilatura.extract(
                cleaned_html_str,
                include_images=True,
                include_links=True,
                include_comments=False,
                include_tables=False,
                output_format='html'
            )

            if not content_html:
                logger.warning(f"Trafilatura returned empty content for {url}")
                return None

            result = {
                "title": title.strip(),
                "content": content_html,
                "excerpt": excerpt.strip(),
                "featured_image_url": featured_image_url,
                "videos": videos
            }
            logger.info(f"Successfully extracted content from {url}. Title: {result['title'][:50]}...")
            return result

        except Exception as e:
            logger.error(f"An unexpected error occurred during extraction for {url}: {e}", exc_info=True)
            return None