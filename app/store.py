#!/usr/bin/env python3
"""
Database management for the application using SQLite.
"""

import sqlite3
import logging
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

class Database:
    """Handles all database operations for the application."""

    def __init__(self, db_path: str = 'data/app.db'):
        """
        Initializes the database connection.

        Args:
            db_path: The path to the SQLite database file.
        """
        db_file = Path(db_path)
        db_file.parent.mkdir(parents=True, exist_ok=True)
        
        self.db_path = db_path
        self.conn = None
        try:
            self.conn = sqlite3.connect(self.db_path, detect_types=sqlite3.PARSE_DECLTYPES, timeout=10)
            self.conn.row_factory = sqlite3.Row
        except sqlite3.Error as e:
            logger.critical(f"Database connection error: {e}")
            raise

    def _get_cursor(self):
        """Returns a cursor for the database connection."""
        if not self.conn:
            raise sqlite3.Error("Database connection is not available.")
        return self.conn.cursor()

    def initialize(self):
        """Creates the necessary tables if they don't exist."""
        logger.info("Initializing database tables if they don't exist...")
        try:
            cursor = self._get_cursor()
            # Tabela para rastrear artigos e seu estado
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS seen_articles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    url TEXT,
                    published_at DATETIME,
                    inserted_at DATETIME DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
                    status TEXT DEFAULT 'NEW', -- NEW, PROCESSING, REWRITTEN, PUBLISHED, FAILED, DEFERRED
                    retry_at DATETIME,
                    fail_count INTEGER DEFAULT 0,
                    UNIQUE(source_id, external_id)
                )
            ''')
            # Tabela para rastrear posts publicados no WordPress
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    seen_article_id INTEGER,
                    wp_post_id INTEGER,
                    created_at DATETIME DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
                    FOREIGN KEY(seen_article_id) REFERENCES seen_articles(id)
                )
            ''')
            # Tabela para rastrear o estado do pipeline (qual feed processar)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS pipeline_state (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            ''')
            cursor.execute("INSERT OR IGNORE INTO pipeline_state (key, value) VALUES ('last_processed_feed_index', '-1')")

            # Tabela para gerenciar o status e cooldown das chaves de API
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS api_key_status (
                    key_hash TEXT PRIMARY KEY,
                    api_key TEXT NOT NULL,
                    category TEXT NOT NULL,
                    is_valid BOOLEAN DEFAULT 1,
                    cooldown_until DATETIME
                )
            ''')

            # Tabela para logs de falhas
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS failures (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id TEXT,
                    article_url TEXT,
                    error_message TEXT,
                    failed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            self.conn.commit()
            logger.info("Database initialized successfully.")
        except sqlite3.Error as e:
            logger.error(f"Database initialization failed: {e}")

    def is_article_published(self, source_id: str, external_id: str) -> bool:
        """
        Checks if an article has already been successfully processed and posted.

        Args:
            source_id: The ID of the feed source.
            external_id: The unique identifier of the article from the feed.

        Returns:
            True if the article is in the 'posts' table, False otherwise.
        """
        try:
            cursor = self._get_cursor()
            cursor.execute(
                "SELECT 1 FROM posts WHERE source_id = ? AND external_id = ?",
                (source_id, external_id)
            )
            return cursor.fetchone() is not None
        except sqlite3.Error as e:
            logger.error(f"Error checking if article is published: {e}")
            return True # Fail safe to avoid reprocessing on DB error

    def save_processed_post(self, source_id: str, external_id: str, wp_post_id: int):
        """Saves a record of a successfully published post."""
        try:
            cursor = self._get_cursor()
            cursor.execute(
                "UPDATE seen_articles SET status = 'PUBLISHED' WHERE source_id = ? AND external_id = ?",
                (source_id, external_id)
            )
            cursor.execute(
                "INSERT INTO posts (seen_article_id, wp_post_id) SELECT id, ? FROM seen_articles WHERE source_id = ? AND external_id = ?",
                (wp_post_id, source_id, external_id)
            )
            self.conn.commit()
            logger.debug(f"Saved post {wp_post_id} for {source_id} to database.")
        except sqlite3.IntegrityError:
            logger.warning(f"Post with external_id {external_id} from {source_id} already exists in posts table.")
        except sqlite3.Error as e:
            logger.error(f"Failed to save processed post: {e}")

    def get_pipeline_state(self, key: str) -> str | None:
        """Gets a value from the pipeline state table."""
        try:
            cursor = self._get_cursor()
            cursor.execute("SELECT value FROM pipeline_state WHERE key = ?", (key,))
            row = cursor.fetchone()
            return row['value'] if row else None
        except sqlite3.Error as e:
            logger.error(f"Failed to get pipeline state for key '{key}': {e}")
            return None

    def set_pipeline_state(self, key: str, value: str):
        """Sets a value in the pipeline state table."""
        try:
            cursor = self._get_cursor()
            cursor.execute("INSERT OR REPLACE INTO pipeline_state (key, value) VALUES (?, ?)", (key, value))
            self.conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Failed to set pipeline state for key '{key}': {e}")

    def update_article_status(self, article_id: int, status: str, retry_at: datetime | None = None):
        """Updates the status of an article in the seen_articles table."""
        try:
            cursor = self._get_cursor()
            if status == 'DEFERRED':
                cursor.execute(
                    "UPDATE seen_articles SET status = ?, retry_at = ?, fail_count = fail_count + 1 WHERE id = ?",
                    (status, retry_at, article_id)
                )
            else:
                 cursor.execute(
                    "UPDATE seen_articles SET status = ? WHERE id = ?",
                    (status, article_id)
                )
            self.conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Failed to update article status for id {article_id}: {e}")

    def get_articles_to_process(self, source_id: str, limit: int) -> list:
        """Gets new or deferred articles for a given feed source."""
        try:
            cursor = self._get_cursor()
            now = datetime.utcnow()
            # Prioritizes deferred articles that are ready for retry, then new ones.
            cursor.execute("""
                SELECT id, external_id, url, status FROM seen_articles
                WHERE source_id = ? AND (status = 'NEW' OR (status = 'DEFERRED' AND retry_at < ?))
                ORDER BY status DESC, published_at DESC
                LIMIT ?
            """, (source_id, now, limit))
            return cursor.fetchall()
        except sqlite3.Error as e:
            logger.error(f"Failed to get articles to process for source_id '{source_id}': {e}")
            return []

    def cleanup_old_entries(self, cutoff_time: datetime) -> int:
        """
        Deletes records from seen_articles and posts older than the cutoff time.
        Only deletes articles with status 'PUBLISHED' or 'FAILED'.

        Args:
            cutoff_time: The datetime threshold. Records older than this will be deleted.

        Returns:
            The number of records deleted from seen_articles.
        """
        try:
            cursor = self._get_cursor()

            # Find IDs of old articles to delete
            cursor.execute(
                "SELECT id FROM seen_articles WHERE inserted_at < ? AND status IN ('PUBLISHED', 'FAILED')",
                (cutoff_time,)
            )
            article_ids_to_delete = [row['id'] for row in cursor.fetchall()]

            if not article_ids_to_delete:
                return 0

            placeholders = ','.join('?' for _ in article_ids_to_delete)

            cursor.execute(f"DELETE FROM posts WHERE seen_article_id IN ({placeholders})", article_ids_to_delete)
            cursor.execute(f"DELETE FROM seen_articles WHERE id IN ({placeholders})", article_ids_to_delete)

            deleted_count = cursor.rowcount
            self.conn.commit()
            return deleted_count
        except sqlite3.Error as e:
            logger.error(f"Error during database cleanup: {e}", exc_info=True)
            self.conn.rollback()
            return 0

    def close(self):
        """Closes the database connection."""
        if self.conn:
            self.conn.close()
            self.conn = None
            logger.info("Database connection closed.")