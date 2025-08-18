from bs4 import BeautifulSoup
import re
from typing import Set

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
    # Procura pelo texto e decompõe o seu elemento pai para remover o bloco inteiro.
    forbidden_texts_re = '|'.join(re.escape(s) for s in FORBIDDEN_TEXT_EXACT)
    if forbidden_texts_re:
        for text_node in soup.find_all(string=re.compile(forbidden_texts_re, re.I)):
            if (text_node or "").strip() in FORBIDDEN_TEXT_EXACT:
                if text_node.parent and text_node.parent.name != '[document]':
                    text_node.parent.decompose()

    # 2. Remove "infobox" (ficha técnica) com base nos rótulos.
    # Heurística: Encontra contêineres com múltiplos rótulos.
    candidates_for_decomposition = []
    for tag in soup.find_all(["div", "section", "aside", "ul", "p"]):
        text_content = " ".join(tag.get_text(separator="\n").split())
        # A regex procura pelo rótulo no início de uma linha ou seguido por dois pontos.
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