"""
Cleanup module for removing old records and temporary files
"""

import logging
import os
import shutil
from datetime import datetime, timedelta
from typing import List

from . import store

logger = logging.getLogger(__name__)


class CleanupManager:
    """Manage cleanup of old records and temporary files"""
    
    def __init__(self, cleanup_after_hours: int = 12):
        self.cleanup_after_hours = cleanup_after_hours
        self.db = store.Database()
    
    def cleanup_database_records(self) -> None:
        """Clean up old database records"""
        logger.info("Starting database cleanup")
        
        try:
            # Convert hours to days for database cleanup
            days_to_keep = max(1, self.cleanup_after_hours // 24)
            self.db.cleanup_old_records(days=days_to_keep)
            
            logger.info("Database cleanup completed successfully")
            
        except Exception as e:
            logger.error(f"Error during database cleanup: {str(e)}")
    
    def cleanup_log_files(self) -> None:
        """Clean up old log files"""
        logger.info("Starting log file cleanup")
        
        log_dirs = ['logs']
        cutoff_time = datetime.now() - timedelta(days=7)  # Keep logs for 7 days
        
        for log_dir in log_dirs:
            if not os.path.exists(log_dir):
                continue
                
            try:
                for filename in os.listdir(log_dir):
                    filepath = os.path.join(log_dir, filename)
                    
                    if os.path.isfile(filepath):
                        # Check file modification time
                        mod_time = datetime.fromtimestamp(os.path.getmtime(filepath))
                        
                        if mod_time < cutoff_time:
                            os.remove(filepath)
                            logger.debug(f"Removed old log file: {filepath}")
                
                logger.info(f"Log file cleanup completed for {log_dir}")
                
            except Exception as e:
                logger.error(f"Error cleaning up log directory {log_dir}: {str(e)}")
    
    def cleanup_temp_files(self) -> None:
        """Clean up temporary files"""
        logger.info("Starting temporary file cleanup")
        
        temp_dirs = ['temp', 'tmp', '/tmp']
        temp_patterns = ['rss_automation_*', 'wp_upload_*']
        
        for temp_dir in temp_dirs:
            if not os.path.exists(temp_dir):
                continue
                
            try:
                for item in os.listdir(temp_dir):
                    item_path = os.path.join(temp_dir, item)
                    
                    # Check if it matches our patterns
                    is_ours = any(
                        item.startswith(pattern.replace('*', '')) 
                        for pattern in temp_patterns
                    )
                    
                    if is_ours and os.path.exists(item_path):
                        # Check if it's old enough
                        mod_time = datetime.fromtimestamp(
                            os.path.getmtime(item_path)
                        )
                        cutoff = datetime.now() - timedelta(hours=1)  # 1 hour old
                        
                        if mod_time < cutoff:
                            if os.path.isfile(item_path):
                                os.remove(item_path)
                                logger.debug(f"Removed temp file: {item_path}")
                            elif os.path.isdir(item_path):
                                shutil.rmtree(item_path)
                                logger.debug(f"Removed temp directory: {item_path}")
                
            except Exception as e:
                logger.error(f"Error cleaning temp directory {temp_dir}: {str(e)}")
        
        logger.info("Temporary file cleanup completed")
    
    def vacuum_database(self) -> None:
        """Vacuum the SQLite database to reclaim space"""
        logger.info("Starting database vacuum")
        
        try:
            with self.db.get_connection() as conn:
                conn.execute("VACUUM")
                conn.commit()
            
            logger.info("Database vacuum completed successfully")
            
        except Exception as e:
            logger.error(f"Error during database vacuum: {str(e)}")
    
    def get_cleanup_stats(self) -> dict:
        """Get cleanup statistics"""
        stats = {
            'database_size': 0,
            'log_files_count': 0,
            'log_files_size': 0,
            'temp_files_count': 0
        }
        
        try:
            # Database size
            if os.path.exists(self.db.db_path):
                stats['database_size'] = os.path.getsize(self.db.db_path)
            
            # Log files
            log_dir = 'logs'
            if os.path.exists(log_dir):
                for filename in os.listdir(log_dir):
                    filepath = os.path.join(log_dir, filename)
                    if os.path.isfile(filepath):
                        stats['log_files_count'] += 1
                        stats['log_files_size'] += os.path.getsize(filepath)
            
            # Temp files
            temp_dirs = ['temp', 'tmp']
            for temp_dir in temp_dirs:
                if os.path.exists(temp_dir):
                    stats['temp_files_count'] += len(os.listdir(temp_dir))
            
        except Exception as e:
            logger.error(f"Error getting cleanup stats: {str(e)}")
        
        return stats
    
    def run_cleanup(self) -> None:
        """Run all cleanup tasks"""
        logger.info(f"Starting cleanup process (cleanup_after_hours={self.cleanup_after_hours})")
        
        # Get stats before cleanup
        stats_before = self.get_cleanup_stats()
        
        # Run cleanup tasks
        self.cleanup_database_records()
        self.cleanup_log_files()
        self.cleanup_temp_files()
        self.vacuum_database()
        
        # Get stats after cleanup
        stats_after = self.get_cleanup_stats()
        
        # Log cleanup summary
        db_size_saved = stats_before['database_size'] - stats_after['database_size']
        log_size_saved = stats_before['log_files_size'] - stats_after['log_files_size']
        
        logger.info("Cleanup process completed")
        logger.info(f"Database size saved: {db_size_saved} bytes")
        logger.info(f"Log files size saved: {log_size_saved} bytes")
        logger.info(f"Temp files before: {stats_before['temp_files_count']}, after: {stats_after['temp_files_count']}")
