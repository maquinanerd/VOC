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

# Load environment variables
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
from app.store import Database

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

# Global variable for automation system status
automation_system = None

def get_db_stats():
    """Get statistics from database"""
    try:
        conn = sqlite3.connect('data/app.db')
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
        last_activity = cursor.fetchone()[0]
        
        if last_activity:
            try:
                last_time = datetime.fromisoformat(last_activity.replace('Z', '+00:00'))
                next_cycle = last_time + timedelta(minutes=15)
                # If next cycle is in the past, schedule for 15 minutes from now
                if next_cycle < datetime.now():
                    next_cycle = datetime.now() + timedelta(minutes=15)
            except:
                next_cycle = datetime.now() + timedelta(minutes=15)
        else:
            next_cycle = datetime.now() + timedelta(minutes=15)
            
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
        log_file = Path('logs/app.log')
        if not log_file.exists():
            return []

        with open(log_file, 'r') as f:
            lines = f.readlines()

        # Get last 50 lines
        recent_lines = lines[-50:] if len(lines) > 50 else lines

        logs = []
        for line in recent_lines:
            line = line.strip()
            if line and ' - ' in line:
                try:
                    parts = line.split(' - ', 3)
                    if len(parts) >= 4:
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
                except:
                    pass

        return logs[-20:]  # Return last 20 logs
    except Exception as e:
        logging.error(f"Error reading logs: {e}")
        return []

@app.route('/')
def dashboard():
    """Main dashboard page"""
    stats = get_db_stats()
    logs = get_recent_logs()

    # Check if system is running by checking recent logs and process status
    try:
        import psutil
        import os

        # Check if there are recent logs indicating the system is active
        is_running = False
        recent_activity = False

        # Look for scheduler started messages in recent logs (last 10 minutes)
        for log in logs[-20:]:  # Check last 20 log entries
            if any(keyword in log['message'] for keyword in [
                "Scheduler started",
                "Starting RSS to WordPress automation system",
                "Pipeline will run every",
                "Added job"
            ]):
                is_running = True
                break

            # Also check for recent processing activity
            if any(keyword in log['message'] for keyword in [
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
            system_status = "Running"
        elif recent_activity:
            system_status = "Processing"
        else:
            system_status = "Stopped"

    except Exception as e:
        logging.error(f"Error determining system status: {e}")
        system_status = "Unknown"


    return render_template('dashboard.html', 
                         stats=stats, 
                         logs=logs, 
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
    # This is a placeholder. A real implementation would check the actual status of the automation system.
    # For now, it defaults to not running as per the original code's implication.
    status = {
        'running': False,
        'next_run': None,
        'jobs': []
    }
    # Example of how to infer status if there were logs indicating startup:
    # if any("Automation system started" in log['message'] for log in get_recent_logs()):
    #     status['running'] = True

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
    # Define feed sources directly since import might fail
    FEED_SOURCES = {
        'screenrant_movies': {
            'name': 'ScreenRant Movies',
            'url': 'https://screenrant.com/feed/movie-news/',
            'category': 'movies'
        },
        'movieweb_movies': {
            'name': 'MovieWeb Movies',
            'url': 'https://movieweb.com/feed/',
            'category': 'movies'
        },
        'collider_movies': {
            'name': 'Collider Movies',
            'url': 'https://collider.com/feed/category/movie-news/',
            'category': 'movies'
        },
        'cbr_movies': {
            'name': 'CBR Movies',
            'url': 'https://www.cbr.com/feed/category/movies/news-movies/',
            'category': 'movies'
        },
        'screenrant_tv': {
            'name': 'ScreenRant TV',
            'url': 'https://screenrant.com/feed/tv-news/',
            'category': 'series'
        },
        'collider_tv': {
            'name': 'Collider TV',
            'url': 'https://collider.com/feed/category/tv-news/',
            'category': 'series'
        },
        'cbr_tv': {
            'name': 'CBR TV',
            'url': 'https://www.cbr.com/feed/category/tv/news-tv/',
            'category': 'series'
        },
        'gamerant_games': {
            'name': 'GameRant Games',
            'url': 'https://gamerant.com/feed/gaming/',
            'category': 'games'
        },
        'thegamer_games': {
            'name': 'TheGamer Games',
            'url': 'https://www.thegamer.com/feed/category/game-news/',
            'category': 'games'
        }
    }

    feed_stats = []
    try:
        conn = sqlite3.connect('data/app.db')
        cursor = conn.cursor()

        for source_id, config in FEED_SOURCES.items():
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
                'name': config['name'],
                'url': config['url'],
                'category': config['category'],
                'recent_articles': recent_count,
                'published_posts': published_count
            })

        conn.close()
    except Exception as e:
        logging.error(f"Error getting feed stats: {e}")
        for source_id, config in FEED_SOURCES.items():
            feed_stats.append({
                'id': source_id,
                'name': config['name'],
                'url': config['url'],
                'category': config['category'],
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
        'log_level': 'INFO',
        'pipeline_interval': '15 minutes',
        'cleanup_interval': '12 hours'
    }

    return render_template('settings.html', settings=settings)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)