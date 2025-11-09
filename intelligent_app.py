#!/usr/bin/env python3
"""
Intelligent Polymarket Chatbot - Flask Web Interface
"""

import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from intelligent_gemini_bot import IntelligentGeminiBot

load_dotenv()

app = Flask(__name__)
CORS(app)

# In-memory log storage (last 100 logs)
app_logs = []
log_id_counter = 0

def log_message(level, message, response_time=None):
    """Add a log message to the in-memory log store."""
    global log_id_counter
    log_id_counter += 1
    log_entry = {
        'id': log_id_counter,
        'level': level,
        'message': message,
        'timestamp': datetime.now().strftime('%H:%M:%S'),
        'responseTime': response_time
    }
    app_logs.append(log_entry)
    # Keep only last 200 logs
    if len(app_logs) > 200:
        app_logs.pop(0)

# Initialize intelligent chatbot with read-only database and log callback
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', 'AIzaSyAxDVBBTQGcR9Em_2vP_8960ayYWl8UFKk')
chatbot = IntelligentGeminiBot(GEMINI_API_KEY, db_path='polymarket_read.db', log_callback=log_message)

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "how", "if", "in",
    "is", "it", "of", "on", "or", "that", "the", "their", "then", "there", "they",
    "this", "to", "what", "when", "where", "which", "who", "will", "with", "would",
    "markets", "market", "prediction", "show", "list", "give"
}

def _extract_keywords(text, limit=6):
    """Extract simple keywords for Kalshi SQL filtering."""
    tokens = re.findall(r"[a-z0-9']+", text.lower())
    keywords = []
    for token in tokens:
        normalized = token.strip("'")
        if len(normalized) >= 3 and normalized not in STOPWORDS and normalized not in keywords:
            keywords.append(normalized)
        if len(keywords) >= limit:
            break
    return keywords

@app.route('/')
def index():
    """Render the main chatbot interface."""
    return render_template('index.html')

@app.route('/api/chat', methods=['POST'])
def chat():
    """Handle chat messages with intelligent strategy selection."""
    try:
        data = request.get_json()
        user_message = data.get('message', '').strip()

        if not user_message:
            return jsonify({'error': 'Empty message'}), 400

        # Log the query
        log_message('query', f'Query: {user_message}')

        # Process with intelligent bot (SQL or Batch strategy)
        import time
        start_time = time.time()
        response = chatbot.process_query(user_message)
        structured_events = chatbot.get_structured_results()
        thinking_trace = chatbot.get_thinking_trace()
        perplexity_queries = chatbot.get_perplexity_queries()
        perplexity_context = chatbot.get_perplexity_context_preview()
        response_time = int((time.time() - start_time) * 1000)  # ms

        log_message('info', f'Response sent ({response_time}ms)', response_time)

        # Extract structured data from response for filtering
        events_data = structured_events if structured_events else extract_events_from_response(response)

        platform_filter = chatbot.get_platform_filter().upper()
        include_polymarket = platform_filter in ('POLYMARKET', 'BOTH')

        polymarket_events = []
        if include_polymarket and events_data:
            for event in events_data:
                event_copy = dict(event)
                event_copy.setdefault('platform', 'polymarket')
                polymarket_events.append(event_copy)

        final_response = response if include_polymarket else ""

        combined_events = polymarket_events
        if not combined_events and not final_response:
            final_response = "No markets found for the requested filters."

        return jsonify({
            'response': final_response,
            'events': combined_events,  # Structured event data for filtering
            'thinking': thinking_trace,
            'perplexity_queries': perplexity_queries,
            'perplexity_context': perplexity_context,
            'platform_filter': platform_filter,
            'success': True
        })

    except Exception as e:
        log_message('error', f'Error: {str(e)}')
        return jsonify({
            'error': str(e),
            'success': False
        }), 500

def extract_events_from_response(response_text):
    """Extract structured event data from markdown response for filtering."""
    import re
    events = []

    # Pattern to match event entries with relevance scores, volume, liquidity
    pattern = r'\d+\.\s+\*\*(.+?)\*\*(?:\s+\(Relevance:\s+(\d+)/100(?:\s+-\s+(.+?))?\))?(?:.*?Volume:\s+\$([0-9,]+))?(?:.*?Liquidity:\s+\$([0-9,.]+))?(?:.*?🔗\s+Link:\s+(https://polymarket\.com/event/[^\s]+))?'

    for match in re.finditer(pattern, response_text, re.DOTALL):
        title = match.group(1).strip()
        relevance = int(match.group(2)) if match.group(2) else None
        reasoning = match.group(3).strip() if match.group(3) else None
        volume_str = match.group(4)
        liquidity_str = match.group(5)
        url = match.group(6)

        volume = float(volume_str.replace(',', '')) if volume_str else 0
        liquidity = float(liquidity_str.replace(',', '')) if liquidity_str else 0

        events.append({
            'title': title,
            'relevance': relevance,
            'reasoning': reasoning,
            'volume': volume,
            'liquidity': liquidity,
            'url': url,
            'platform': 'polymarket'
        })

    return events

@app.route('/api/stats')
def stats():
    """Get database statistics."""
    try:
        import sqlite3
        from db_sync import ReadTracker

        with ReadTracker():
            conn = sqlite3.connect('polymarket_read.db')
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(*) FROM events WHERE is_active = 1")
            active_count = cursor.fetchone()[0]

            cursor.execute("SELECT SUM(volume) FROM events WHERE is_active = 1")
            total_volume = cursor.fetchone()[0] or 0

            cursor.execute("SELECT COUNT(DISTINCT domain) FROM events WHERE is_active = 1")
            categories = cursor.fetchone()[0]

            conn.close()
        
        return jsonify({
            'total_events': active_count,
            'total_volume': total_volume,
            'categories': categories
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/top-events')
def top_events():
    """Get top events by volume using SQL strategy."""
    try:
        limit = int(request.args.get('limit', 10))

        # Use SQL strategy directly for top events
        import sqlite3
        from db_sync import ReadTracker

        with ReadTracker():
            conn = sqlite3.connect('polymarket_read.db')
            cursor = conn.cursor()

            cursor.execute(f"""
                SELECT id, title, slug, domain, volume, liquidity, outcome_prices
                FROM events
                WHERE is_active = 1
                ORDER BY volume DESC
                LIMIT {limit}
            """)

            results = cursor.fetchall()
            conn.close()
        
        events_data = [{
            'id': r[0],
            'title': r[1],
            'slug': r[2],
            'domain': r[3],
            'volume': float(r[4]) if r[4] else 0,
            'liquidity': float(r[5]) if r[5] else 0,
            'outcome_prices': r[6],
            'url': f'https://polymarket.com/event/{r[2]}'
        } for r in results]
        
        return jsonify({'events': events_data, 'count': len(events_data)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/health')
def health():
    """Health check endpoint."""
    try:
        import sqlite3
        from db_sync import ReadTracker

        with ReadTracker():
            conn = sqlite3.connect('polymarket_read.db')
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM events WHERE is_active = 1")
            active_events = cursor.fetchone()[0]
            conn.close()
        
        return jsonify({
            'status': 'healthy',
            'database': 'connected',
            'active_events': active_events,
            'strategy': 'intelligent (SQL + Batch)',
            'schedulers': {
                'update_market_data': 'running (20s)',
                'sync_events': 'running (30m)'
            }
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500

@app.route('/logs')
def logs():
    """Display Flask application logs."""
    return render_template('logs.html')

@app.route('/api/logs')
def get_logs():
    """Get recent application logs."""
    return jsonify({'logs': app_logs[-100:]})

@app.route('/api/filter-events', methods=['POST'])
def filter_events():
    """Filter events based on criteria."""
    try:
        data = request.get_json()
        events = data.get('events', [])
        filters = data.get('filters', {})

        # Apply filters
        filtered_events = events

        # Filter by volume
        if filters.get('min_volume'):
            min_vol = float(filters['min_volume'])
            filtered_events = [e for e in filtered_events if e.get('volume', 0) >= min_vol]

        if filters.get('max_volume'):
            max_vol = float(filters['max_volume'])
            filtered_events = [e for e in filtered_events if e.get('volume', 0) <= max_vol]

        # Filter by liquidity
        if filters.get('min_liquidity'):
            min_liq = float(filters['min_liquidity'])
            filtered_events = [e for e in filtered_events if e.get('liquidity', 0) >= min_liq]

        if filters.get('max_liquidity'):
            max_liq = float(filters['max_liquidity'])
            filtered_events = [e for e in filtered_events if e.get('liquidity', 0) <= max_liq]

        # Filter by relevance
        if filters.get('min_relevance'):
            min_rel = int(filters['min_relevance'])
            filtered_events = [e for e in filtered_events if e.get('relevance') and e['relevance'] >= min_rel]

        # Search by keyword
        if filters.get('search'):
            search_term = filters['search'].lower()
            filtered_events = [e for e in filtered_events if
                              search_term in (e.get('title') or '').lower() or
                              search_term in (e.get('reasoning') or '').lower()]

        # Sort
        sort_by = filters.get('sort_by', 'relevance')
        reverse = filters.get('sort_order', 'desc') == 'desc'

        if sort_by == 'volume':
            filtered_events.sort(key=lambda x: x.get('volume', 0), reverse=reverse)
        elif sort_by == 'liquidity':
            filtered_events.sort(key=lambda x: x.get('liquidity', 0), reverse=reverse)
        elif sort_by == 'relevance':
            filtered_events.sort(key=lambda x: x.get('relevance', 0) if x.get('relevance') else 0, reverse=reverse)

        return jsonify({
            'filtered_events': filtered_events,
            'count': len(filtered_events),
            'success': True
        })

    except Exception as e:
        import traceback
        import sys
        error_details = traceback.format_exc()
        sys.stderr.write(f"\n{'='*80}\nFilter error:\n{error_details}\n{'='*80}\n")
        sys.stderr.flush()
        return jsonify({'error': str(e), 'details': error_details, 'success': False}), 500

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5001))
    debug = os.getenv('DEBUG', 'False').lower() == 'true'

    print("=" * 70)
    print("🧠 INTELLIGENT POLYMARKET CHATBOT")
    print("=" * 70)
    print(f"🌐 Web Interface: http://localhost:{port}")
    print(f"⚡ Strategy: Intelligent (SQL + Batch)")
    print(f"📊 SQL queries: <1 second")
    print(f"🔍 Semantic search: 15-30 seconds")
    print(f"📈 Real-time updates: Every 20 seconds")
    print("=" * 70)

    app.run(host='0.0.0.0', port=port, debug=debug)
