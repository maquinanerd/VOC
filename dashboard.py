#!/usr/bin/env python3
"""
Dashboard web para o sistema de automação RSS-para-WordPress
"""

import os
import sys
import sqlite3
import json
from datetime import datetime, timedelta
from pathlib import Path
from flask import Flask, render_template, jsonify, request, redirect, url_for, flash
import logging
from collections import deque

# Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # Fallback to manual loading if python-dotenv is not available
    env_file = Path('.env')
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    value = value.strip('"').strip("'")
                    os.environ[key] = value

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import application modules
try:
    from app.config import RSS_FEEDS, PIPELINE_ORDER, SCHEDULE_CONFIG
except ImportError:
    # Define empty fallbacks to allow the app to start, but show an error.
    print("="*80)
    print("ERROR: Could not import configuration from 'app.config'.")
    print("Please ensure 'app/config.py' exists and contains:")
    print(" - RSS_FEEDS (dict)")
    print(" - PIPELINE_ORDER (list)")
    print(" - SCHEDULE_CONFIG (dict)")
    print("="*80)
    RSS_FEEDS, PIPELINE_ORDER, SCHEDULE_CONFIG = {}, [], {}

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / 'data' / 'app.db'
LOG_FILE_PATH = BASE_DIR / 'logs' / 'app.log'

def get_db_stats():
    """Get statistics from database"""
    try:
        if not DB_PATH.exists():
            raise FileNotFoundError(f"Database not found at {DB_PATH}")
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # Get article counts
        cursor.execute('SELECT COUNT(*) FROM seen_articles')
        seen_count = cursor.fetchone()[0]

        cursor.execute('SELECT COUNT(*) FROM posts')
        published_count = cursor.fetchone()[0]

        cursor.execute('SELECT COUNT(*) FROM failures')
        failure_count = cursor.fetchone()[0]

        # Get recent posts
        cursor.execute('''
            SELECT source_id, external_id, wp_post_id, created_at 
            FROM posts 
            ORDER BY created_at DESC 
            LIMIT 10
        ''')
        recent_posts = cursor.fetchall()

        # Get API usage stats
        cursor.execute('''
            SELECT api_type, SUM(usage_count) as usage_count
            FROM api_usage 
            WHERE last_used > datetime('now', '-24 hours')
            GROUP BY api_type
        ''')
        api_usage = cursor.fetchall()

        # Calculate next cycle time based on last activity or 15 minutes from now
        cursor.execute('''
            SELECT MAX(inserted_at) FROM seen_articles 
            WHERE inserted_at > datetime('now', '-2 hours')
        ''')
        row = cursor.fetchone()
        last_activity = row[0] if row and row[0] else None

        check_interval = SCHEDULE_CONFIG.get('check_interval', 15)

        if last_activity:
            try:
                # SQLite datetime format is 'YYYY-MM-DD HH:MM:SS'
                last_time = datetime.strptime(last_activity, '%Y-%m-%d %H:%M:%S')
                next_cycle = last_time + timedelta(minutes=check_interval)
                # If next cycle is in the past, schedule for 15 minutes from now
                if next_cycle < datetime.now():
                    next_cycle = datetime.now() + timedelta(minutes=check_interval)
            except (ValueError, TypeError):
                next_cycle = datetime.now() + timedelta(minutes=check_interval)
        else:
            next_cycle = datetime.now() + timedelta(minutes=check_interval)
            
        next_cycle_str = next_cycle.strftime('%H:%M:%S')

        conn.close()

        return {
            'seen_articles': seen_count,
            'published_posts': published_count,
            'failures': failure_count,
            'recent_posts': recent_posts,
            'api_usage': dict(api_usage),
            'next_cycle': next_cycle_str
        }
    except Exception as e:
        logging.error(f"Error getting database stats: {e}")
        return {
            'seen_articles': 0,
            'published_posts': 0,
            'failures': 0,
            'recent_posts': [],
            'api_usage': {},
            'next_cycle': 'N/A'
        }

def get_recent_logs():
    """Get recent log entries"""
    try:
        log_file = LOG_FILE_PATH
        if not log_file.exists():
            return []

        with open(log_file, 'r', encoding='utf-8') as f:
            # Use deque for a memory-efficient way to get the last 50 lines.
            recent_lines = deque(f, 50)

        logs = []
        for line in recent_lines:
            line = line.strip()
            if line and ' - ' in line:
                try:
                    parts = line.split(' - ', 3)
                    if len(parts) == 4:
                        timestamp = parts[0]
                        logger_name = parts[1]
                        level = parts[2]
                        message = parts[3]

                        logs.append({
                            'timestamp': timestamp,
                            'logger': logger_name,
                            'level': level,
                            'message': message
                        })
                except Exception:
                    pass

        return list(reversed(logs))
    except Exception as e:
        logging.error(f"Error reading logs: {e}")
        return []

def _get_system_status():
    """Determines the system status by checking logs and running processes."""
    try:
        import psutil
    except ImportError:
        logging.warning("psutil not installed, status check will be limited.")
        return "Unknown (psutil not installed)"

    try:
        logs = get_recent_logs()
        is_running = False
        recent_activity = False

        # Look for scheduler started messages in recent logs (last 10 minutes)
        for log in logs:
            msg = log.get('message', '').lower()
            if any(keyword in msg for keyword in [
                "Scheduler started",
                "Starting RSS to WordPress automation system",
                "Pipeline will run every",
                "Added job"
            ]):
                is_running = True
                break

            # Also check for recent processing activity
            msg = log.get('message', '').lower()
            if any(keyword in msg for keyword in [
                "Processing feed",
                "Found new articles",
                "Published to WordPress"
            ]):
                recent_activity = True

        # Check if main.py process is running (backup method)
        if not is_running:
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    if proc.info['cmdline'] and 'main.py' in ' '.join(proc.info['cmdline']):
                        is_running = True
                        break
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

        if is_running:
            return "Running"
        elif recent_activity:
            return "Processing"
        else:
            return "Stopped"

    except Exception as e:
        logging.error(f"Error determining system status: {e}")
        return "Unknown"

@app.route('/')
def dashboard():
    """Main dashboard page"""
    stats = get_db_stats()
    logs = get_recent_logs()
    system_status = _get_system_status()

    return render_template('dashboard.html', 
                         stats=stats, 
                         logs=logs[:20], # Show latest 20 logs
                         system_status=system_status)

@app.route('/api/stats')
def api_stats():
    """API endpoint for statistics"""
    return jsonify(get_db_stats())

@app.route('/api/logs')
def api_logs():
    """API endpoint for logs"""
    return jsonify(get_recent_logs())

@app.route('/api/system/status')
def api_system_status():
    """Get system status"""
    status_str = _get_system_status()
    stats = get_db_stats()

    status = {
        'running': status_str in ["Running", "Processing"],
        'status_text': status_str,
        'next_run': stats.get('next_cycle', 'N/A'),
        'jobs': []
    }
    return jsonify(status)

@app.route('/api/system/start', methods=['POST'])
def api_start_system():
    """Start the automation system"""
    return jsonify({'success': False, 'message': 'Controle do sistema não disponível nesta versão'})

@app.route('/api/system/stop', methods=['POST'])
def api_stop_system():
    """Stop the automation system"""
    return jsonify({'success': False, 'message': 'Controle do sistema não disponível nesta versão'})

@app.route('/api/system/run-now', methods=['POST'])
def api_run_now():
    """Force a pipeline run now"""
    return jsonify({'success': False, 'message': 'Execução manual não disponível nesta versão'})

@app.route('/feeds')
def feeds_page():
    """Feeds management page"""
    feed_stats = []
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        for source_id in PIPELINE_ORDER:
            config = RSS_FEEDS.get(source_id)
            if not config:
                continue

            cursor.execute('''
                SELECT COUNT(*) FROM seen_articles 
                WHERE source_id = ? AND inserted_at > datetime('now', '-24 hours')
            ''', (source_id,))
            recent_count = cursor.fetchone()[0]

            cursor.execute('''
                SELECT COUNT(*) FROM posts 
                WHERE source_id = ?
            ''', (source_id,))
            published_count = cursor.fetchone()[0]

            feed_stats.append({
                'id': source_id,
                'name': source_id.replace('_', ' ').title(),
                'url': config.get('urls', ['N/A'])[0],
                'category': config['category'],
                'recent_articles': recent_count,
                'published_posts': published_count
            })

        conn.close()
    except Exception as e:
        logging.error(f"Error getting feed stats: {e}")
        # Fallback with no stats on DB error
        for source_id in PIPELINE_ORDER:
            config = RSS_FEEDS.get(source_id, {})
            feed_stats.append({
                'id': source_id,
                'name': source_id.replace('_', ' ').title(),
                'url': config.get('urls', ['N/A'])[0],
                'category': config.get('category', 'N/A'),
                'recent_articles': 0,
                'published_posts': 0
            })

    return render_template('feeds.html', feeds=feed_stats)

@app.route('/settings')
def settings_page():
    """Settings page"""
    settings = {
        'wordpress_url': os.environ.get('WORDPRESS_URL', ''),
        'wordpress_user': os.environ.get('WORDPRESS_USER', ''),
        'gemini_keys_count': len([k for k in os.environ.keys() if k.startswith('GEMINI_')]),
        'log_level': os.environ.get('LOG_LEVEL', 'INFO'),
        'pipeline_interval': f"{SCHEDULE_CONFIG.get('check_interval', 'N/A')} minutes",
        'cleanup_interval': f"{SCHEDULE_CONFIG.get('cleanup_after_hours', 'N/A')} hours"
    }

    return render_template('settings.html', settings=settings)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)