"""
SQLite database storage for tracking and deduplication
"""

import logging
import sqlite3
import hashlib
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import os

logger = logging.getLogger(__name__)


class Database:
    """SQLite database for article tracking and deduplication"""
    
    def __init__(self, db_path: str = "data/app.db"):
        self.db_path = db_path
        
        # Ensure data directory exists
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
    
    def get_connection(self) -> sqlite3.Connection:
        """Get database connection"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def initialize(self) -> None:
        """Initialize database tables"""
        logger.info("Initializing database")
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Seen articles table for deduplication
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS seen_articles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    published_at TIMESTAMP,
                    inserted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(source_id, external_id)
                )
            """)
            
            # Processed posts table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    wp_post_id INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(source_id, external_id)
                )
            """)
            
            # Failures table for error tracking
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS failures (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id TEXT NOT NULL,
                    external_id TEXT,
                    error_type TEXT NOT NULL,
                    error_message TEXT,
                    url TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # API usage tracking
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS api_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    api_type TEXT NOT NULL,
                    api_key_hash TEXT NOT NULL,
                    usage_count INTEGER DEFAULT 1,
                    last_used TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    date DATE DEFAULT (DATE('now'))
                )
            """)
            
            # Create indexes for better performance
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_seen_articles_source_external ON seen_articles(source_id, external_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_posts_source_external ON posts(source_id, external_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_failures_created ON failures(created_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_api_usage_date ON api_usage(date)")
            
            conn.commit()
            logger.info("Database initialized successfully")
    
    def mark_article_seen(self, source_id: str, external_id: str, published_at: Optional[datetime] = None) -> None:
        """Mark an article as seen to prevent reprocessing"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            try:
                cursor.execute("""
                    INSERT OR IGNORE INTO seen_articles (source_id, external_id, published_at)
                    VALUES (?, ?, ?)
                """, (source_id, external_id, published_at))
                
                conn.commit()
                
            except sqlite3.Error as e:
                logger.error(f"Error marking article as seen: {str(e)}")
    
    def is_article_seen(self, source_id: str, external_id: str) -> bool:
        """Check if an article has been seen before"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT 1 FROM seen_articles 
                WHERE source_id = ? AND external_id = ?
            """, (source_id, external_id))
            
            return cursor.fetchone() is not None
    
    def save_processed_post(self, source_id: str, external_id: str, wp_post_id: int) -> None:
        """Save information about a successfully processed post"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            try:
                cursor.execute("""
                    INSERT OR REPLACE INTO posts (source_id, external_id, wp_post_id)
                    VALUES (?, ?, ?)
                """, (source_id, external_id, wp_post_id))
                
                conn.commit()
                logger.debug(f"Saved processed post: {source_id}/{external_id} -> WP:{wp_post_id}")
                
            except sqlite3.Error as e:
                logger.error(f"Error saving processed post: {str(e)}")
    
    def log_failure(self, source_id: str, error_type: str, error_message: str, 
                   external_id: Optional[str] = None, url: Optional[str] = None) -> None:
        """Log a processing failure"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            try:
                cursor.execute("""
                    INSERT INTO failures (source_id, external_id, error_type, error_message, url)
                    VALUES (?, ?, ?, ?, ?)
                """, (source_id, external_id, error_type, error_message, url))
                
                conn.commit()
                
            except sqlite3.Error as e:
                logger.error(f"Error logging failure: {str(e)}")
    
    def track_api_usage(self, api_type: str, api_key: str) -> None:
        """Track API usage for monitoring"""
        # Hash the API key for privacy
        api_key_hash = hashlib.sha256(api_key.encode()).hexdigest()[:16]
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            try:
                # Check if entry exists for today
                cursor.execute("""
                    SELECT id, usage_count FROM api_usage 
                    WHERE api_type = ? AND api_key_hash = ? AND date = DATE('now')
                """, (api_type, api_key_hash))
                
                row = cursor.fetchone()
                
                if row:
                    # Update existing record
                    cursor.execute("""
                        UPDATE api_usage 
                        SET usage_count = usage_count + 1, last_used = CURRENT_TIMESTAMP
                        WHERE id = ?
                    """, (row['id'],))
                else:
                    # Create new record
                    cursor.execute("""
                        INSERT INTO api_usage (api_type, api_key_hash, usage_count)
                        VALUES (?, ?, 1)
                    """, (api_type, api_key_hash))
                
                conn.commit()
                
            except sqlite3.Error as e:
                logger.error(f"Error tracking API usage: {str(e)}")
    
    def get_recent_posts(self, hours: int = 24) -> List[Dict[str, Any]]:
        """Get posts created in the last N hours"""
        cutoff = datetime.now() - timedelta(hours=hours)
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT source_id, external_id, wp_post_id, created_at
                FROM posts 
                WHERE created_at > ?
                ORDER BY created_at DESC
            """, (cutoff,))
            
            return [dict(row) for row in cursor.fetchall()]
    
    def get_failure_stats(self, hours: int = 24) -> Dict[str, int]:
        """Get failure statistics for the last N hours"""
        cutoff = datetime.now() - timedelta(hours=hours)
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT error_type, COUNT(*) as count
                FROM failures 
                WHERE created_at > ?
                GROUP BY error_type
            """, (cutoff,))
            
            return {row['error_type']: row['count'] for row in cursor.fetchall()}
    
    def cleanup_old_records(self, days: int = 30) -> None:
        """Clean up old records"""
        cutoff = datetime.now() - timedelta(days=days)
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Clean up old seen articles
            cursor.execute("DELETE FROM seen_articles WHERE inserted_at < ?", (cutoff,))
            seen_deleted = cursor.rowcount
            
            # Clean up old failures
            cursor.execute("DELETE FROM failures WHERE created_at < ?", (cutoff,))
            failures_deleted = cursor.rowcount
            
            # Clean up old API usage records
            cutoff_date = cutoff.date()
            cursor.execute("DELETE FROM api_usage WHERE date < ?", (cutoff_date,))
            api_deleted = cursor.rowcount
            
            conn.commit()
            
            logger.info(f"Cleanup completed: {seen_deleted} seen articles, {failures_deleted} failures, {api_deleted} API usage records")
