import logging
from datetime import datetime, timedelta

from app.config import PIPELINE_ORDER, RSS_FEEDS, SCHEDULE_CONFIG
from app.store import Database
from app.feeds import FeedReader
from app.extractor import ContentExtractor
from app.rewriter import Rewriter
from app.tags import TagGenerator
from app.categorizer import WordPressCategorizer
from app.wordpress import WordPressPublisher
from app.media import MediaHandler
from app.ai_processor import AIProcessor, AllKeysOnCooldownError

logger = logging.getLogger(__name__)

def run_pipeline_cycle():
    """
    Executa um ciclo completo do pipeline para um único feed,
    seguindo a ordem de round-robin.
    """
    db = Database()
    
    # 1. Determinar qual feed processar (Round-Robin)
    try:
        last_index_str = db.get_pipeline_state('last_processed_feed_index')
        last_index = int(last_index_str) if last_index_str is not None else -1
        
        next_index = (last_index + 1) % len(PIPELINE_ORDER)
        feed_id = PIPELINE_ORDER[next_index]
        feed_config = RSS_FEEDS[feed_id]
        
        logger.info(f"Iniciando ciclo do pipeline para o feed: {feed_id}")

        # Inicializa os componentes do pipeline
        feed_reader = FeedReader(db)
        extractor = ContentExtractor()
        ai_processor = AIProcessor(db)
        rewriter = Rewriter()
        tag_generator = TagGenerator()
        categorizer = WordPressCategorizer()
        media_handler = MediaHandler()
        publisher = WordPressPublisher(db)

        # 2. Ler o feed e encontrar novos artigos
        new_articles = feed_reader.fetch_and_filter(feed_id, feed_config['urls'])
        
        if not new_articles:
            logger.info(f"Nenhum artigo novo encontrado para {feed_id}.")
            db.set_pipeline_state('last_processed_feed_index', str(next_index))
            return

        logger.info(f"Encontrados {len(new_articles)} novos artigos para {feed_id}.")

        # 3. Processar um número limitado de artigos por ciclo
        articles_to_process = new_articles[:SCHEDULE_CONFIG['max_articles_per_feed']]
        deferred_count = 0

        for article in articles_to_process:
            try:
                logger.info(f"Processando artigo: {article.title} de {feed_id}")

                # 4. Extrair conteúdo
                extracted_data = extractor.extract(article.link)
                if not extracted_data or not extracted_data.get('content'):
                    logger.warning(f"Falha ao extrair conteúdo de {article.link}")
                    continue

                # 5. Gerar Tags
                tags = tag_generator.generate(extracted_data['content'])
                tags_text = ", ".join(tags)

                # 6. Reescrever com IA
                try:
                    rewritten_text = ai_processor.rewrite_content(
                        title=article.title,
                        excerpt=article.summary,
                        tags_text=tags_text,
                        content=extracted_data['content'],
                        category=feed_config['category']
                    )
                except AllKeysOnCooldownError:
                    logger.error(f"Todas as chaves de IA para a categoria '{feed_config['category']}' estão em cooldown. Abortando o ciclo para este feed.")
                    # Não atualiza o índice, para tentar este feed novamente no próximo ciclo
                    return

                if not rewritten_text:
                    logger.warning(f"Processamento de IA falhou para {article.link}. Adicionando à fila de adiados.")
                    retry_at = datetime.utcnow() + timedelta(minutes=60)
                    db.update_article_status(article.db_id, 'DEFERRED', retry_at=retry_at)
                    deferred_count += 1
                    if deferred_count >= SCHEDULE_CONFIG['max_deferred_articles_per_feed']:
                        logger.warning(f"Limite de adiamentos ({deferred_count}) atingido para o feed {feed_id}. Encerrando o ciclo para este feed.")
                        # Não atualiza o índice, para tentar este feed novamente no próximo ciclo
                        return
                    continue

                # 7. Processar a saída da IA
                processed_content = rewriter.process(rewritten_text)
                if not processed_content:
                    logger.error(f"Falha ao processar a saída da IA para {article.link}")
                    continue

                # 8. Tratar imagem destacada
                featured_media_id = media_handler.handle_featured_image(
                    extracted_data.get('image_url'),
                    processed_content['title']
                )

                # 9. Determinar categorias e tags do WordPress
                wp_category_ids = categorizer.get_category_ids(feed_id)
                wp_tags = publisher.get_or_create_tags(tags)

                # 10. Publicar no WordPress
                post_id = publisher.publish(
                    title=processed_content['title'],
                    content=processed_content['content'],
                    excerpt=processed_content['excerpt'],
                    category_ids=wp_category_ids,
                    tag_ids=[tag['id'] for tag in wp_tags],
                    featured_media_id=featured_media_id,
                    original_url=article.link
                )

                if post_id:
                    db.save_processed_post(feed_id, article.id, post_id)

            except Exception as e:
                logger.exception(f"Erro inesperado ao processar o artigo {article.link}: {e}")

        # 11. Atualizar o estado do pipeline para o próximo feed
        db.set_pipeline_state('last_processed_feed_index', str(next_index))
        logger.info(f"Ciclo do pipeline para {feed_id} concluído.")

    except Exception as e:
        logger.exception(f"Erro crítico no ciclo do pipeline: {e}")