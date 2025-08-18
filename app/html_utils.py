import re
import logging
from typing import List, Dict
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs

logger = logging.getLogger(__name__)

YOUTUBE_HOSTS = {
    "youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "www.youtu.be"
}

def _yt_id_from_url(url: str) -> str | None:
    if not url:
        return None
    try:
        u = urlparse(url)
        host = (u.hostname or "").lower()
        if host not in YOUTUBE_HOSTS:
            return None
        if u.path.startswith("/embed/"):
            return u.path.split("/")[2].split("?")[0]
        if u.path.startswith("/shorts/"):
            return u.path.split("/")[2].split("?")[0]
        if host.endswith("youtu.be"):
            return u.path.lstrip("/").split("?")[0]
        if u.path == "/watch":
            q = parse_qs(u.query)
            return (q.get("v") or [None])[0]
    except Exception:
        pass
    return None

def strip_credits_and_normalize_youtube(html: str) -> str:
    """
    - Remove linhas de crédito (figcaption/p/span iniciando com Crédito/Credito/Fonte)
    - Converte <iframe> do YouTube em um <p> com a URL watch (WordPress faz o oEmbed)
    - Remove/“desembrulha” <figure> vazias ou que apenas envolvem o embed
    """
    if not html:
        return html

    soup = BeautifulSoup(html, "lxml")

    # 1) Remover “Crédito:”, “Credito:”, “Fonte:”
    for node in soup.find_all(["figcaption", "p", "span"]):
        t = (node.get_text() or "").strip()
        tl = t.lower()
        if tl.startswith(("crédito:", "credito:", "fonte:")):
            node.decompose()

    # 2) Iframes -> URL watch (oEmbed)
    for iframe in soup.find_all("iframe"):
        vid = _yt_id_from_url(iframe.get("src", ""))
        if vid:
            p = soup.new_tag("p")
            p.string = f"https://www.youtube.com/watch?v={vid}"
            iframe.replace_with(p)

    # 3) Limpar <figure> que só envolvem o embed ou ficaram vazias
    for fig in list(soup.find_all("figure")):
        has_img = fig.find("img") is not None
        if not has_img:
            # único filho é <p> com URL do youtube?
            children_tags = [c for c in fig.contents if getattr(c, "name", None)]
            only_p = (len(children_tags) == 1 and getattr(children_tags[0], "name", None) == "p")
            p = children_tags[0] if only_p else None
            p_text = (p.get_text().strip() if p else "")
            if only_p and ("youtube.com/watch" in p_text or "youtu.be/" in p_text):
                fig.replace_with(p)
            elif not fig.get_text(strip=True):
                fig.unwrap()

    return soup.body.decode_contents() if soup.body else str(soup)