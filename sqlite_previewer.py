#!/usr/bin/env python3
"""Lightweight SQLite database viewer."""

import argparse
import sqlite3
import time
from pathlib import Path

from flask import Flask, jsonify, render_template, request


def resolve_db_path(raw_path: str) -> Path:
    """Validate and resolve the provided SQLite database path."""
    if not raw_path:
        raise ValueError('Database path is required')

    path = Path(raw_path).expanduser()

    if not path.exists() or not path.is_file():
        raise ValueError(f'Database file not found: {path}')

    if path.suffix.lower() not in {'.db', '.sqlite', '.sqlite3'}:
        raise ValueError('Only .db, .sqlite, or .sqlite3 files are supported')

    return path.resolve()


def quote_identifier(identifier: str) -> str:
    """Return a double-quoted SQLite identifier."""
    return f'"{identifier.replace("\"", "\"\"")}"'


def create_app(database_path: Path) -> Flask:
    app = Flask(__name__)
    app.config['DATABASE_PATH'] = database_path

    def connect() -> sqlite3.Connection:
        uri = f'file:{database_path.as_posix()}?mode=ro'
        return sqlite3.connect(uri, uri=True, check_same_thread=False)

    @app.route('/')
    def index():
        return render_template('sqlite_previewer.html', db_path=str(database_path))

    @app.route('/api/schema')
    def schema():
        try:
            conn = connect()
            cursor = conn.cursor()

            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
            tables = [row[0] for row in cursor.fetchall()]

            schema_payload = {}
            for table in tables:
                cursor.execute(f"PRAGMA table_info({quote_identifier(table)})")
                columns = cursor.fetchall()
                cursor.execute(f"SELECT COUNT(*) FROM {quote_identifier(table)}")
                row_count = cursor.fetchone()[0]

                schema_payload[table] = {
                    'count': row_count,
                    'columns': [
                        {
                            'name': col[1],
                            'type': col[2],
                            'pk': bool(col[5])
                        }
                        for col in columns
                    ]
                }

            conn.close()

            return jsonify({'success': True, 'schema': schema_payload})
        except Exception as exc:
            return jsonify({'success': False, 'error': str(exc)}), 500

    @app.route('/api/query', methods=['POST'])
    def run_query():
        payload = request.get_json() or {}
        query = (payload.get('query') or '').strip()
        limit = payload.get('limit')

        if not query:
            return jsonify({'success': False, 'error': 'Query is required'}), 400

        if not query.lower().startswith('select'):
            return jsonify({'success': False, 'error': 'Only SELECT statements are permitted'}), 400

        base_query = query.rstrip(';\n\r\t ')

        limit_clause = None
        if limit is not None:
            try:
                limit_value = int(limit)
                if limit_value > 0:
                    limit_clause = limit_value
            except (TypeError, ValueError):
                return jsonify({'success': False, 'error': 'Limit must be an integer'}), 400

        if limit_clause:
            query = f'SELECT * FROM ({base_query}) LIMIT {limit_clause}'
        else:
            query = base_query

        try:
            conn = connect()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            start = time.perf_counter()
            cursor.execute(query)
            rows = cursor.fetchall()
            elapsed = time.perf_counter() - start

            columns = rows[0].keys() if rows else [desc[0] for desc in cursor.description or []]
            data = [dict(row) for row in rows]

            conn.close()

            return jsonify(
                {
                    'success': True,
                    'columns': columns,
                    'data': data,
                    'count': len(data),
                    'execution_time': elapsed,
                }
            )
        except Exception as exc:
            return jsonify({'success': False, 'error': str(exc)}), 500

    return app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Simple SQLite database viewer')
    parser.add_argument(
        '--db',
        default='/Users/jaidevshah/prediction-data/polymarket.db',
        help='Path to the SQLite database file (default: %(default)s)',
    )
    parser.add_argument('--host', default='127.0.0.1', help='Host to bind the development server')
    parser.add_argument('--port', type=int, default=5001, help='Port for the development server')
    return parser.parse_args()


def main():
    args = parse_args()
    db_path = resolve_db_path(args.db)
    app = create_app(db_path)
    app.run(host=args.host, port=args.port, debug=True)


if __name__ == '__main__':
    main()
