#!/usr/bin/env python3
"""
Database management for the application using SQLite.
"""

import sqlite3
import logging
from datetime import datetime
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
            # Table for successfully published posts
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    wp_post_id INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(source_id, external_id)
                )
            ''')
            # Table for all articles seen in feeds
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS seen_articles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    inserted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(source_id, external_id)
                )
            ''')
            # Table for processing failures
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS failures (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id TEXT,
                    article_url TEXT,
                    error_message TEXT,
                    failed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            # Table for API usage tracking
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS api_usage (
                    api_type TEXT PRIMARY KEY,
                    usage_count INTEGER DEFAULT 0,
                    last_used TIMESTAMP
                )
            ''')
            self.conn.commit()
            logger.info("Database initialized successfully.")
        except sqlite3.Error as e:
            logger.error(f"Database initialization failed: {e}")

    def is_article_processed(self, source_id: str, external_id: str) -> bool:
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
            logger.error(f"Error checking if article is processed: {e}")
            return True # Fail safe to avoid reprocessing on DB error

    def save_processed_post(self, source_id: str, external_id: str, wp_post_id: int):
        """Saves a record of a successfully published post."""
        try:
            cursor = self._get_cursor()
            cursor.execute(
                "INSERT INTO posts (source_id, external_id, wp_post_id) VALUES (?, ?, ?)",
                (source_id, external_id, wp_post_id)
            )
            self.conn.commit()
            logger.debug(f"Saved post {wp_post_id} for {source_id} to database.")
        except sqlite3.IntegrityError:
            logger.warning(f"Post with external_id {external_id} from {source_id} already exists in posts table.")
        except sqlite3.Error as e:
            logger.error(f"Failed to save processed post: {e}")

    def close(self):
        """Closes the database connection."""
        if self.conn:
            self.conn.close()
            self.conn = None
            logger.info("Database connection closed.")