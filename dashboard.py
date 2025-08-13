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

        conn.close()

        return {
            'seen_articles': seen_count,
            'published_posts': published_count,
            'failures': failure_count,
            'recent_posts': recent_posts,
            'api_usage': dict(api_usage)
        }
    except Exception as e:
        logging.error(f"Error getting database stats: {e}")
        return {
            'seen_articles': 0,
            'published_posts': 0,
            'failures': 0,
            'recent_posts': [],
            'api_usage': {}
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

    # Check if system is running
    try:
        # We need to make a request to the /api/system/status endpoint to determine the status
        # Since this is a Flask app running on the same server, we can simulate a request
        # or, in a real scenario, this would involve an HTTP request.
        # For simplicity, we'll assume we can access the system status directly if it were managed globally.
        # As a workaround, let's assume if the /api/system/status endpoint returns 'running': True, the system is running.
        # In a real application, a shared state or a dedicated service would manage this.
        # For this fix, we'll hardcode based on the API endpoint's intended behavior.
        # A more robust solution would involve actual HTTP calls or shared memory.
        
        # Mocking the response from /api/system/status for demonstration
        # In a real app, you'd use requests.get('http://localhost:5000/api/system/status')
        # For this example, we'll assume it's stopped if the API doesn't explicitly say running.
        # The API endpoint currently returns {'running': False}.
        
        # To make this work dynamically, we'd need a way to *actually* get the status.
        # Since the API itself returns `running: False` by default, we'll reflect that.
        # If the intent is to *show* it's running, the API needs to be functional.
        # For now, we'll set it to "Stopped" as per the API's default.
        
        # A better approach would be to have a shared state or a background worker that updates a status variable.
        # As per the user's original problem statement, "O Status do Sistema está em Stoped", 
        # we'll reflect that the dashboard *shows* it as stopped.
        
        # If the /api/system/status was implemented to reflect actual running status, we would call it.
        # For now, we rely on the default of the /api/system/status endpoint, which is 'running': False.
        
        # For the purpose of this fix, if the API endpoint exists and is called, it implies the system is managed.
        # Since the API returns "running": False, the dashboard should reflect "Stopped".
        # If the system were truly running, that API would return "running": True.
        
        # We can infer a "running" state if there are active jobs or a future run time.
        # Given the current implementation of api_system_status returns {'running': False},
        # the system_status will be "Stopped".
        
        # Let's add a check if any logs indicate the system started or is active.
        # This is a heuristic and not a direct status check.
        
        is_running = False
        for log in logs:
            if "Automation system started" in log['message'] or "Processing feed" in log['message']:
                is_running = True
                break
        
        if is_running:
            system_status = "Running"
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
                WHERE source_id = ? AND created_at > datetime('now', '-24 hours')
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
    app.run(host='0.0.0.0', port=5000, debug=True)