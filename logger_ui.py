"""
Web-based UI for Query Logger
Provides a browser interface to view and manage query logs.
"""
import os
from flask import Flask, render_template, jsonify, request
from datetime import datetime
import re

app = Flask(__name__)
LOG_FILE = 'query_execution.log'


def parse_log_file():
    """Parse the log file into structured query entries."""
    if not os.path.exists(LOG_FILE):
        return []

    with open(LOG_FILE, 'r') as f:
        content = f.read()

    queries = []

    # Find all query blocks by looking for the pattern: separator + QUERY: + separator
    separator = '=' * 80
    pattern = f'{separator}\nQUERY:'

    # Split content into individual query entries
    parts = content.split(pattern)

    for part in parts[1:]:  # Skip first empty part
        if not part.strip():
            continue

        # Add back the "QUERY:" prefix
        full_block = 'QUERY:' + part

        query_data = {
            'query': '',
            'timestamp': '',
            'strategy': '',
            'reason': '',
            'sql_queries': [],
            'ai_prompts': [],
            'results_count': 0,
            'time_elapsed': 0.0
        }

        lines = full_block.split('\n')

        # Parse query and timestamp
        for line in lines:
            if line.startswith('QUERY:'):
                query_data['query'] = line.replace('QUERY:', '').strip()
            elif line.startswith('TIMESTAMP:'):
                query_data['timestamp'] = line.replace('TIMESTAMP:', '').strip()
            elif line.startswith('STRATEGY CHOSEN:'):
                query_data['strategy'] = line.replace('STRATEGY CHOSEN:', '').strip()
            elif line.startswith('REASON:'):
                query_data['reason'] = line.replace('REASON:', '').strip()

        # Parse SQL queries and AI prompts
        j = 0
        while j < len(lines):
            line = lines[j]

            if line.startswith('--- SQL QUERY ---'):
                sql_query = {'platform': '', 'query': ''}
                j += 1
                while j < len(lines) and not lines[j].startswith('---'):
                    if lines[j].startswith('Platform:'):
                        sql_query['platform'] = lines[j].replace('Platform:', '').strip()
                    elif lines[j].startswith('Query:'):
                        sql_query['query'] = lines[j].replace('Query:', '').strip()
                    j += 1
                if sql_query['platform'] and sql_query['query']:
                    query_data['sql_queries'].append(sql_query)
                continue

            elif line.startswith('--- AI PROMPT:'):
                prompt_name = line.replace('--- AI PROMPT:', '').replace('---', '').strip()
                ai_prompt = {'name': prompt_name, 'input': '', 'output': ''}
                j += 1

                # Parse input
                if j < len(lines) and lines[j].startswith('Input ('):
                    j += 1
                    input_lines = []
                    while j < len(lines) and not lines[j].startswith('Output ('):
                        input_lines.append(lines[j])
                        j += 1
                    ai_prompt['input'] = '\n'.join(input_lines).strip()

                # Parse output
                if j < len(lines) and lines[j].startswith('Output ('):
                    j += 1
                    output_lines = []
                    while j < len(lines) and not lines[j].startswith('---') and not lines[j].startswith('RESULTS'):
                        output_lines.append(lines[j])
                        j += 1
                    ai_prompt['output'] = '\n'.join(output_lines).strip()

                if ai_prompt['name']:
                    query_data['ai_prompts'].append(ai_prompt)
                continue

            elif line.startswith('--- RESULTS ---'):
                j += 1
                while j < len(lines):
                    if lines[j].startswith('Markets Found:'):
                        try:
                            query_data['results_count'] = int(lines[j].replace('Markets Found:', '').strip())
                        except:
                            pass
                    elif lines[j].startswith('Time Elapsed:'):
                        try:
                            time_str = lines[j].replace('Time Elapsed:', '').replace('s', '').strip()
                            query_data['time_elapsed'] = float(time_str)
                        except:
                            pass
                    j += 1
                break

            j += 1

        if query_data['query']:
            queries.append(query_data)

    # Reverse to show newest first
    return list(reversed(queries))


def get_stats():
    """Get statistics about logged queries."""
    queries = parse_log_file()

    total_queries = len(queries)
    sql_count = sum(1 for q in queries if 'SQL' in q['strategy'])
    ai_count = sum(1 for q in queries if 'AI' in q['strategy'])

    total_time = sum(q['time_elapsed'] for q in queries)
    avg_time = total_time / total_queries if total_queries > 0 else 0

    sql_times = [q['time_elapsed'] for q in queries if 'SQL' in q['strategy']]
    ai_times = [q['time_elapsed'] for q in queries if 'AI' in q['strategy']]

    avg_sql_time = sum(sql_times) / len(sql_times) if sql_times else 0
    avg_ai_time = sum(ai_times) / len(ai_times) if ai_times else 0

    return {
        'total_queries': total_queries,
        'sql_count': sql_count,
        'ai_count': ai_count,
        'total_time': round(total_time, 2),
        'avg_time': round(avg_time, 2),
        'avg_sql_time': round(avg_sql_time, 2),
        'avg_ai_time': round(avg_ai_time, 2)
    }


@app.route('/')
def index():
    """Main page showing all queries."""
    return render_template('logger_dashboard.html')


@app.route('/api/queries')
def get_queries():
    """API endpoint to get all queries."""
    queries = parse_log_file()
    return jsonify(queries)


@app.route('/api/stats')
def get_statistics():
    """API endpoint to get statistics."""
    stats = get_stats()
    return jsonify(stats)


@app.route('/api/clear_log', methods=['POST'])
def clear_log():
    """Clear the log file."""
    try:
        with open(LOG_FILE, 'w') as f:
            f.write("")
        return jsonify({'success': True, 'message': 'Log file cleared'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/export')
def export_log():
    """Export log file."""
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'r') as f:
            content = f.read()
        return jsonify({'success': True, 'content': content})
    return jsonify({'success': False, 'message': 'Log file not found'})


if __name__ == '__main__':
    # Create templates directory if it doesn't exist
    os.makedirs('templates', exist_ok=True)

    print("=" * 80)
    print("🖥️  QUERY LOGGER WEB UI")
    print("=" * 80)
    print(f"📊 Viewing logs from: {LOG_FILE}")
    print("🌐 Starting web server...")
    print("=" * 80)
    print("\n✅ Server running at: http://localhost:5001")
    print("📱 Open this URL in your browser to view the dashboard\n")
    print("Press Ctrl+C to stop the server")
    print("=" * 80)

    app.run(debug=True, port=5001, host='0.0.0.0')
