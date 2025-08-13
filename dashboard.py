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

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

def get_db_stats():
    """Get statistics from database"""
    try:
        conn = sqlite3.connect('data/app.db')
        cursor = conn.cursor()
        
        # Get article counts
        cursor.execute('SELECT COUNT(*) FROM seen_articles')
        seen_count = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM posts WHERE status = "published"')
        published_count = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM failures')
        failure_count = cursor.fetchone()[0]
        
        # Get recent posts
        cursor.execute('''
            SELECT title, source_id, created_at, status 
            FROM posts 
            ORDER BY created_at DESC 
            LIMIT 10
        ''')
        recent_posts = cursor.fetchall()
        
        # Get API usage stats
        cursor.execute('''
            SELECT category, COUNT(*) as usage_count
            FROM api_usage 
            WHERE created_at > datetime('now', '-24 hours')
            GROUP BY category
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
    system_status = "Running" if automation_system and automation_system.scheduler.running else "Stopped"
    
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
    global automation_system
    
    status = {
        'running': automation_system and automation_system.scheduler.running if automation_system else False,
        'next_run': None,
        'jobs': []
    }
    
    if automation_system and automation_system.scheduler.running:
        jobs = automation_system.scheduler.get_jobs()
        for job in jobs:
            status['jobs'].append({
                'id': job.id,
                'name': job.name,
                'next_run': job.next_run_time.isoformat() if job.next_run_time else None
            })
    
    return jsonify(status)

@app.route('/api/system/start', methods=['POST'])
def api_start_system():
    """Start the automation system"""
    global automation_system
    
    try:
        if not automation_system:
            automation_system = RSSAutomationSystem()
        
        if not automation_system.scheduler.running:
            automation_system.start()
            return jsonify({'success': True, 'message': 'Sistema iniciado com sucesso'})
        else:
            return jsonify({'success': False, 'message': 'Sistema já está rodando'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erro ao iniciar sistema: {str(e)}'})

@app.route('/api/system/stop', methods=['POST'])
def api_stop_system():
    """Stop the automation system"""
    global automation_system
    
    try:
        if automation_system and automation_system.scheduler.running:
            automation_system.scheduler.shutdown()
            return jsonify({'success': True, 'message': 'Sistema parado com sucesso'})
        else:
            return jsonify({'success': False, 'message': 'Sistema não está rodando'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erro ao parar sistema: {str(e)}'})

@app.route('/api/system/run-now', methods=['POST'])
def api_run_now():
    """Force a pipeline run now"""
    global automation_system
    
    try:
        if not automation_system:
            automation_system = RSSAutomationSystem()
        
        # Run pipeline in background
        automation_system.run_pipeline_cycle()
        return jsonify({'success': True, 'message': 'Pipeline executado manualmente'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erro ao executar pipeline: {str(e)}'})

@app.route('/feeds')
def feeds_page():
    """Feeds management page"""
    # Get feed sources from main module
    from app.main import FEED_SOURCES
    
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
                WHERE source_id = ? AND status = "published"
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