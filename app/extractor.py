import logging
import trafilatura
from bs4 import BeautifulSoup
import requests
from typing import Dict, Optional, Any, Set
from urllib.parse import urljoin, urlparse, parse_qs
import json
import re

from .config import USER_AGENT

logger = logging.getLogger(__name__)

YOUTUBE_DOMAINS = (
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "youtu.be",
    "www.youtu.be",
)

PRIORITY_CDN_DOMAINS = (
    "static1.srcdn.com",
    "static1.colliderimages.com",
    "static1.cbrimages.com",
    "static1.moviewebimages.com",
    "static0.gamerantimages.com",
    "static1.gamerantimages.com",
    "static2.gamerantimages.com",
    "static3.gamerantimages.com",
    "static1.thegamerimages.com",
)

FORBIDDEN_TEXT_EXACT: Set[str] = {
    "Your comment has not been saved",
}

FORBIDDEN_LABELS: Set[str] = {
    "Release Date", "Runtime", "Director", "Directors", "Writer", "Writers",
    "Producer", "Producers", "Cast"
}

JUNK_IMAGE_PATTERNS = ("placeholder", "sprite", "icon", "emoji", ".svg")

def _parse_srcset(srcset: str):
    """
    Parses a srcset attribute and returns the URL of the largest image.
    Example: "url1 320w, url2 640w, url3 1200w" -> "url3"
    """
    best = None
    best_w = -1
    for part in (srcset or "").split(","):
        part = part.strip()
        if not part:
            continue
        tokens = part.split()
        url = tokens[0]
        w = 0
        if len(tokens) > 1 and tokens[1].endswith("w"):
            try:
                w = int(tokens[1][:-1])
            except Exception:
                w = 0
        if w >= best_w:
            best_w = w
            best = url
    return best

def is_small(u: str) -> bool:
    """Checks if a URL likely points to a small or irrelevant image."""
    if not u:
        return True
    try:
        # Check for width/height query parameters
        query = urlparse(u).query
        params = parse_qs(query)
        w = int(params.get("w", [0])[0] or 0)
        h = int(params.get("h", [0])[0] or 0)
        if (w and w < 300) or (h and h < 200):
            logger.debug(f"Filtering out small image by query param: {u} (w={w}, h={h})")
            return True
        # Check for common placeholder/junk patterns
        if any(pat in u.lower() for pat in JUNK_IMAGE_PATTERNS):
            logger.debug(f"Filtering out image by pattern (junk/svg): {u}")
            return True
    except (ValueError, IndexError):
        pass # Ignore parsing errors in query params
    return False

def _abs(u: str, base: str) -> str | None:
    """Converts a URL to an absolute URL, returning None for invalid inputs."""
    if not u:
        return None
    u = u.strip()
    if not u or u.startswith("data:"):
        return None
    return urljoin(base, u)

def _extract_from_style(style_attr: str) -> Optional[str]:
    """Extracts a URL from a 'background-image: url(...)' style attribute."""
    if not style_attr:
        return None
    # Regex to find url(...) and handle optional quotes
    match = re.search(r"url\((['\"]?)(.*?)\1\)", style_attr)
    if match:
        return match.group(2)
    return None

def collect_images_from_article(soup: BeautifulSoup, base_url: str) -> list[str]:
    """
    for img in soup.find_all("img"):
        cand = None
        for attr in ("src", "data-src", "data-original", "data-lazy-src", "data-image", "data-img-url"):
            if cand := img.get(attr):
                break
        if not cand and img.get("srcset"):
            cand = _parse_srcset(img.get("srcset"))
        if cand := _abs(cand, base_url):
            urls.append(cand)

    # 2) <picture><source srcset="..."> tags
    for source in soup.select("picture source[srcset]"):
        if pick := _parse_srcset(source.get("srcset")):
            if pick := _abs(pick, base_url):
                urls.append(pick)

    # 3) divs/figures with data-* attributes (common on ScreenRant/Collider)
    for node in soup.select('[data-img-url], [data-image], [data-src], [data-original]'):
        cand = node.get("data-img-url") or node.get("data-image") or node.get("data-src") or node.get("data-original")
        if cand := _abs(cand, base_url):
            urls.append(cand)

    # De-duplicate while preserving order
    return list(dict.fromkeys(urls))


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

    def _remove_forbidden_blocks(self, soup: BeautifulSoup) -> None:
        """
        Removes unwanted blocks like comment confirmations and technical spec boxes
        from the extracted article content.
        """
        # 1. Remove any node containing the exact text of a comment warning
        for t in soup.find_all(string=True):
            s = (t or "").strip()
            if not s:
                continue
            if s in FORBIDDEN_TEXT_EXACT:
                try:
                    # Try to remove the parent, which is likely the container
                    t.parent.decompose()
                    logger.debug(f"Removed forbidden text block: '{s}'")
                except Exception:
                    # If parent is gone or something else happens, just continue
                    pass

        # 2. Remove "infobox" like technical sheets based on labels
        candidates = []
        for tag in soup.find_all(["div", "section", "aside", "ul", "ol"]):
            text = " ".join(tag.get_text(separator="\n").split())
            # Heuristic: presence of >=2 known labels
            lbl_count = sum(1 for lbl in FORBIDDEN_LABELS if re.search(rf"(^|\n)\s*{re.escape(lbl)}\s*(\n|:|$)", text, flags=re.I))
            if lbl_count >= 2:
                candidates.append(tag)

        if candidates:
            logger.info(f"Found {len(candidates)} candidate infobox(es) to remove.")
        for c in candidates:
            try:
                c.decompose()
            except Exception:
                pass

        # 3. Also remove isolated lines with these labels at the paragraph/list level
        for tag in soup.find_all(["p", "li", "span", "h3", "h4"]):
            if not tag.parent: continue # Already decomposed
            s = (tag.get_text() or "").strip().rstrip(':').strip()
            if s in FORBIDDEN_TEXT_EXACT or s in FORBIDDEN_LABELS:
                tag.decompose()

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

            # 6. Post-process the extracted content to remove forbidden blocks
            article_soup = BeautifulSoup(content_html, 'lxml')
            self._remove_forbidden_blocks(article_soup)

            # 7. Collect all images using the advanced collector from the cleaned article soup
            all_image_urls = collect_images_from_article(article_soup, base_url=url)
            logger.info(f"Collected {len(all_image_urls)} images from article body.")

            # The body tag is sometimes added by BeautifulSoup, we only want the contents
            if article_soup.body:
                final_content_html = article_soup.body.decode_contents()
            else:
                final_content_html = str(article_soup)

            result = {
                "title": title.strip(),
                "content": final_content_html,
                "excerpt": excerpt.strip(),
                "featured_image_url": featured_image_url,
                "images": all_image_urls,
                "videos": videos,
                "source_url": url,
            }
            logger.info(f"Successfully extracted and cleaned content from {url}. Title: {result['title'][:50]}...")
            return result

        except Exception as e:
            logger.error(f"An unexpected error occurred during extraction for {url}: {e}", exc_info=True)
            return None