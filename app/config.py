import os
from dotenv import load_dotenv
from tenacity import wait_exponential, stop_after_attempt

# Carrega variáveis de ambiente de um arquivo .env
load_dotenv()

PIPELINE_ORDER = [
    'screenrant_movies', 'screenrant_tv',
    'movieweb_movies',
    'collider_movies', 'collider_tv',
    'cbr_movies', 'cbr_tv',
    'gamerant_games', 'thegamer_games',
]

RSS_FEEDS = {
    'screenrant_movies': {'urls': ['https://screenrant.com/feed/movie-news/'], 'category': 'movies'},
    'screenrant_tv':     {'urls': ['https://screenrant.com/feed/tv-news/'],    'category': 'series'},
    'movieweb_movies':   {'urls': ['https://movieweb.com/feed/'],               'category': 'movies'},
    'collider_movies':   {'urls': ['https://collider.com/feed/category/movie-news/'], 'category': 'movies'},
    'collider_tv':       {'urls': ['https://collider.com/feed/category/tv-news/'],    'category': 'series'},
    'cbr_movies':        {'urls': ['https://www.cbr.com/feed/category/movies/news-movies/'], 'category': 'movies'},
    'cbr_tv':            {'urls': ['https://www.cbr.com/feed/category/tv/news-tv/'],         'category': 'series'},
    'gamerant_games':    {'urls': ['https://gamerant.com/feed/gaming/'],        'category': 'games'},
    'thegamer_games':    {'urls': ['https://www.thegamer.com/feed/category/game-news/'], 'category': 'games'}
}

USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'

# --- Configuração da IA ---
AI_MODELS = {
    'primary': os.getenv('AI_PRIMARY_MODEL', 'gemini-1.5-pro-latest'),
    'fallback': os.getenv('AI_FALLBACK_MODEL', 'gemini-1.5-flash-latest'),
}

AI_GENERATION_CONFIG = {
    'temperature': 0.6,
    'top_p': 1.0,
    'max_output_tokens': 4096,
}

# --- Configuração do WordPress ---
WORDPRESS_CONFIG = {
    'url': os.getenv('WORDPRESS_URL'),
    'user': os.getenv('WORDPRESS_USER'),
    'password': os.getenv('WORDPRESS_PASSWORD')
}

WORDPRESS_CATEGORIES = {
    'Notícias': 20, 'Filmes': 24, 'Séries': 21, 'Games': 73,
}

# --- Configuração do Agendador e Pipeline ---
SCHEDULE_CONFIG = {
    'check_interval': int(os.getenv('CHECK_INTERVAL_MINUTES', 15)),
    'max_articles_per_feed': int(os.getenv('MAX_ARTICLES_PER_FEED', 3)),
    'api_call_delay': int(os.getenv('API_CALL_DELAY_SECONDS', 30)),
    'cleanup_after_hours': int(os.getenv('CLEANUP_AFTER_HOURS', 12))
}

PIPELINE_CONFIG = {
    'images_mode': os.getenv('IMAGES_MODE', 'hotlink'),  # 'hotlink' | 'download_upload'
    'attribution_policy': 'Via {domain}',
    'publisher_name': 'Máquina Nerd',
    'publisher_logo_url': 'https://www.maquinanerd.com.br/wp-content/uploads/2023/11/logo-maquina-nerd-400px.png'
}

# --- Configuração de Retentativas ---
RETRY_CONFIG = {
    'wait': wait_exponential(multiplier=1, min=2, max=10),
    'stop': stop_after_attempt(3),
}