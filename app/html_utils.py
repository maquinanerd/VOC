import logging
import re
from typing import List, Dict, Set
from urllib.parse import urlparse

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Textos que NUNCA podem aparecer
FORBIDDEN_TEXT_EXACT: Set[str] = {
    "Your comment has not been saved",
}

# Rótulos típicos de ficha técnica/infobox que devem ser removidos
FORBIDDEN_LABELS: Set[str] = {
    "Release Date", "Runtime", "Director", "Directors", "Writer", "Writers",
    "Producer", "Producers", "Cast"
}

def hard_filter_forbidden_html(html: str) -> str:
    """
    Remove mensagens de UI e qualquer bloco/caixa de 'ficha técnica' do HTML final.
    Este é um filtro "hard kill" aplicado após a reescrita da IA para garantir a limpeza.
    """
    if not html:
        return ""

    soup = BeautifulSoup(html, 'lxml')

    # 1. Remove qualquer nó que contenha textos de UI proibidos.
    forbidden_texts_re = '|'.join(re.escape(s) for s in FORBIDDEN_TEXT_EXACT)
    if forbidden_texts_re:
        for text_node in soup.find_all(string=re.compile(forbidden_texts_re, re.I)):
            if (text_node or "").strip() in FORBIDDEN_TEXT_EXACT:
                if text_node.parent and text_node.parent.name != '[document]':
                    text_node.parent.decompose()

    # 2. Remove "infobox" (ficha técnica) com base nos rótulos.
    candidates_for_decomposition = []
    for tag in soup.find_all(["div", "section", "aside", "ul", "p"]):
        text_content = " ".join(tag.get_text(separator="\n").split())
        label_count = sum(
            1 for label in FORBIDDEN_LABELS
            if re.search(rf"(^|\n)\s*{re.escape(label)}\s*:", text_content, re.IGNORECASE)
        )
        if label_count >= 2:
            candidates_for_decomposition.append(tag)

    for candidate in candidates_for_decomposition:
        if candidate.parent:
            candidate.decompose()

    # 3. Remove também linhas/parágrafos isolados que são apenas um rótulo.
    for tag in soup.find_all(["p", "li", "h3", "h4", "div", "strong", "b"]):
        if not tag.parent: continue
        tag_text = (tag.get_text() or "").strip().rstrip(':').strip()
        if tag_text in FORBIDDEN_LABELS:
            if tag.parent.name in ['p', 'li'] and len(tag.parent.get_text(strip=True)) == len(tag_text):
                 tag.parent.decompose()
            else:
                 tag.decompose()

    if soup.body:
        return soup.body.decode_contents()
    else:
        return str(soup)

def merge_images_into_content(html_content: str, image_urls: List[str], max_images: int = 6) -> str:
    """
    Garante que o conteúdo HTML tenha imagens. Se nenhuma tag <img> estiver presente,
    injeta imagens da lista fornecida no conteúdo.

    Args:
        html_content: A string de conteúdo HTML.
        image_urls: Uma lista de URLs de imagem originais para injetar potencialmente.
        max_images: O número máximo de imagens a serem injetadas.

    Returns:
        O conteúdo HTML, possivelmente com imagens injetadas.
    """
    if not image_urls or not html_content:
        return html_content

    soup = BeautifulSoup(html_content, 'html.parser')

    if soup.find('img'):
        logger.info("O conteúdo já contém tags <img>. Pulando a injeção de imagens.")
        return html_content

    paragraphs = soup.find_all('p')
    if not paragraphs:
        logger.warning("Nenhuma tag <p> encontrada para injetar imagens. Retornando conteúdo original.")
        return html_content

    logger.info(f"Nenhuma tag <img> encontrada. Tentando injetar até {max_images} imagens.")
    
    images_to_inject = image_urls[:max_images]
    injection_points = len(paragraphs)
    injection_interval = max(1, injection_points // (len(images_to_inject) + 1))

    injected_count = 0
    figures_to_insert = []
    for i, image_url in enumerate(images_to_inject):
        injection_index = (i + 1) * injection_interval
        if injection_index < len(paragraphs):
            target_p = paragraphs[injection_index]
            
            figure = soup.new_tag('figure', attrs={'class': 'wp-block-image size-large'})
            img = soup.new_tag('img', src=image_url, alt="", loading="lazy", decoding="async")
            figcaption = soup.new_tag('figcaption')
            figure.append(img)
            figure.append(figcaption)
            
            figures_to_insert.append((target_p, figure))

    for target_p, figure in figures_to_insert:
        target_p.insert_after(figure)
        injected_count += 1

    if injected_count > 0:
        logger.info(f"Injetou com sucesso {injected_count} imagens no conteúdo.")
        return str(soup)
    
    return html_content

def add_credit_to_figures(html_content: str, source_url: str) -> str:
    """
    Adiciona uma legenda "Crédito: {domínio}" a qualquer elemento <figure>
    que ainda não tenha uma legenda não vazia.

    Args:
        html_content: A string de conteúdo HTML.
        source_url: A URL do artigo original para extrair o domínio.

    Returns:
        O conteúdo HTML com créditos adicionados às figuras.
    """
    if not html_content or not source_url:
        return html_content

    try:
        domain = urlparse(source_url).netloc.replace('www.', '')
    except Exception:
        logger.warning(f"Não foi possível analisar o domínio de source_url: {source_url}")
        return html_content

    credit_text = f"Crédito: {domain}"
    soup = BeautifulSoup(html_content, 'html.parser')
    
    credited_count = 0
    for figure in soup.find_all('figure'):
        figcaption = figure.find('figcaption')
        if figcaption and not figcaption.get_text(strip=True):
            figcaption.string = credit_text
            credited_count += 1
        elif not figcaption:
            new_figcaption = soup.new_tag('figcaption')
            new_figcaption.string = credit_text
            figure.append(new_figcaption)
            credited_count += 1
            
    if credited_count > 0:
        logger.info(f"Adicionou/atualizou créditos para {credited_count} figuras.")

    return str(soup)

def rewrite_img_srcs_with_wp(html_content: str, url_map: Dict[str, str]) -> str:
    """
    Substitui URLs de imagens externas em tags <img> por suas novas URLs do WordPress.

    Args:
        html_content: A string de conteúdo HTML.
        url_map: Um dicionário mapeando {original_url: wordpress_url}.

    Returns:
        O conteúdo HTML com as fontes das imagens atualizadas.
    """
    if not url_map or not html_content:
        return html_content

    soup = BeautifulSoup(html_content, 'html.parser')
    rewritten_count = 0
    for img in soup.find_all('img'):
        original_src = img.get('src')
        if original_src and original_src in url_map:
            img['src'] = url_map[original_src]
            if img.has_attr('srcset'):
                img['srcset'] = url_map[original_src]
            rewritten_count += 1
            
    if rewritten_count > 0:
        logger.info(f"Reescreveu {rewritten_count} URLs de imagem para apontar para a biblioteca de mídia do WordPress.")

    return str(soup)