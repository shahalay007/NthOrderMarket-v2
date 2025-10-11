"""
Intelligent Gemini-powered Polymarket chatbot with dual strategy:
1. SQL-first for data queries (fast)
2. Batch processing for semantic queries (accurate)
Gemini decides which approach to use
Uses read-only database replica for query operations.
"""
import os
import json
import sqlite3
import time
from datetime import datetime, timedelta
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor, as_completed
import google.generativeai as genai
from .database import Database, Event
from sqlalchemy import text, or_
from .db_sync_service import ReadTracker

DEFAULT_DISPLAY_LIMIT = 20

class IntelligentGeminiBot:
    def __init__(self, api_key, db_path='polymarket_read.db', log_callback=None):
        """Initialize intelligent Gemini chatbot with read-only database."""
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel('gemini-2.5-pro')
        self.db = Database(db_path=db_path)
        self.db_path = db_path
        self.log_callback = log_callback  # Callback for logging to Flask

        # Cache last structured payload for MCP clients
        self.last_structured_results = []

        # Cache for stats
        self._stats_cache = None
        self._stats_cache_time = None
        self._cache_ttl = timedelta(minutes=5)

    def _log(self, level, message):
        """Log a message via callback if available."""
        if self.log_callback:
            self.log_callback(level, message)

    def _call_gemini(self, prompt, step_name):
        """Call Gemini API with logging."""
        self._log('info', f'🤖 Gemini: {step_name}')

        # Log prompt preview (first 200 chars)
        prompt_preview = prompt[:200].replace('\n', ' ') + ('...' if len(prompt) > 200 else '')
        self._log('info', f'📤 Input ({len(prompt)} chars): {prompt_preview}')

        response = self.model.generate_content(prompt)
        result = response.text.strip()

        # Log response preview (first 300 chars)
        result_preview = result[:300].replace('\n', ' ') + ('...' if len(result) > 300 else '')
        self._log('info', f'📥 Output ({len(result)} chars): {result_preview}')
        return result

    def _reset_structured_results(self):
        """Reset cached structured payload."""
        self.last_structured_results = []

    def _record_structured_results(self, events):
        """Store structured payload for downstream clients."""
        self.last_structured_results = events or []

    def get_structured_results(self):
        """Expose structured payload to callers."""
        return list(self.last_structured_results)

    @staticmethod
    def _normalize_numeric(value):
        """Best-effort float normalization."""
        if value is None:
            return 0.0
        if isinstance(value, (int, float)):
            return float(value)
        cleaned = str(value).replace('$', '').replace(',', '').strip()
        if not cleaned:
            return 0.0
        try:
            return float(cleaned)
        except ValueError:
            return 0.0

    @staticmethod
    def _build_market_url(slug, event_id):
        """Generate Polymarket URL."""
        if slug:
            return f'https://polymarket.com/event/{slug}'
        if event_id:
            return f'https://polymarket.com/event/{event_id}'
        return None

    def _structured_from_mapping(self, mapping, strategy='sql', relevance=None, reasoning=None):
        """Normalize mapping row into structured dict."""
        if mapping is None:
            return None
        event_id = mapping.get('id')
        slug = mapping.get('slug')
        return {
            'id': str(event_id) if event_id is not None else None,
            'title': mapping.get('title'),
            'slug': slug,
            'domain': mapping.get('domain'),
            'section': mapping.get('section'),
            'subsection': mapping.get('subsection'),
            'volume': self._normalize_numeric(mapping.get('volume')),
            'liquidity': self._normalize_numeric(mapping.get('liquidity')),
            'outcome_prices': mapping.get('outcome_prices'),
            'relevance': relevance,
            'reasoning': reasoning,
            'url': self._build_market_url(slug, event_id),
            'strategy': strategy
        }

    def _structured_from_event(self, event, strategy='batch'):
        """Normalize ORM event to structured dict."""
        if event is None:
            return None
        relevance = getattr(event, 'relevance_score', None)
        reasoning = getattr(event, 'relevance_reasoning', None)
        return {
            'id': str(event.id) if getattr(event, 'id', None) is not None else None,
            'title': getattr(event, 'title', None),
            'slug': getattr(event, 'slug', None),
            'domain': getattr(event, 'domain', None),
            'section': getattr(event, 'section', None),
            'subsection': getattr(event, 'subsection', None),
            'volume': self._normalize_numeric(getattr(event, 'volume', None)),
            'liquidity': self._normalize_numeric(getattr(event, 'liquidity', None)),
            'outcome_prices': getattr(event, 'outcome_prices', None),
            'relevance': relevance,
            'reasoning': reasoning,
            'url': self._build_market_url(getattr(event, 'slug', None), getattr(event, 'id', None)),
            'strategy': strategy
        }

    def _get_db_schema(self):
        """Get database schema for SQL generation."""
        return """
DATABASE SCHEMA:
Table: events

IMPORTANT: These are the ONLY columns available in the database. DO NOT use any other columns:
- id (TEXT, PRIMARY KEY) - Event ID
- slug (TEXT, UNIQUE) - URL slug
- title (TEXT) - Event title/question
- domain (TEXT) - Top-level category (e.g., "Politics", "Sports", "Finance", "Entertainment & Culture", "Geopolitics & World Events", "Technology", "Miscellaneous")
- section (TEXT) - Second-level category (e.g., "US Politics", "American Football (NFL)")
- subsection (TEXT) - Third-level category (e.g., "Elections", "Game Outcome")
- description (TEXT) - Detailed event description (nullable)
- section_tag_id (INTEGER) - Section tag ID
- subsection_tag_id (INTEGER) - Subsection tag ID
- is_active (BOOLEAN) - Whether event is active (0 or 1)
- volume (INTEGER) - Trading volume in USD
- last_trade_date (TEXT) - Last trade date (ISO format)
- outcome_prices (TEXT) - JSON array of outcome prices
- last_trade_price (INTEGER) - Last trade price
- best_bid (INTEGER) - Best bid price
- best_ask (INTEGER) - Best ask price
- liquidity (INTEGER) - Total market liquidity
- liquidity_num (INTEGER) - Numeric liquidity
- liquidity_clob (INTEGER) - CLOB liquidity
- open_interest (INTEGER) - Open interest
- created_at (DATETIME) - Creation timestamp
- updated_at (DATETIME) - Last update timestamp
- last_synced (DATETIME) - Last sync timestamp

CRITICAL: Do NOT include columns like 'price', 'resolved', or any other columns not listed above. They do not exist in the database.

Common query patterns:
- Top volume: SELECT * FROM events WHERE is_active=1 ORDER BY volume DESC
- Recent: SELECT * FROM events WHERE is_active=1 ORDER BY updated_at DESC
- Active only: WHERE is_active = 1
- Filter by domain: WHERE domain LIKE '%Politics%'
- Search title: WHERE LOWER(title) LIKE '%keyword%'
- Use broad keywords with LIKE for better matching (e.g., '%tax%' instead of '%tax increase%')
"""
    
    def analyze_query_all_in_one(self, user_query):
        """Combined: Analyze intent, output format, strategy, required columns, and domain filter in ONE call."""
        try:
            combined_prompt = f"""Analyze this user query and provide ALL decision points:

USER QUERY: {user_query}

{self._get_db_schema()}

AVAILABLE DOMAINS FOR FILTERING:
1. Sports (NFL, NBA, Soccer, Tennis, etc.)
2. Politics (Elections, Government, Politicians)
3. Finance (Markets, Crypto, Economy, Fed, Interest Rates)
4. Entertainment & Culture (Movies, Music, Celebrities, Singers, Artists, Awards)
5. Geopolitics & World Events (International Relations, Wars, Conflicts)
6. Technology (AI, Software, Tech Companies, Social Media)
7. Miscellaneous (Everything else, catch-all category)

Provide the following in your response:

1. INTENT (what user wants, filters, sorting)
2. OUTPUT_FORMAT (what to show in response)
3. USER_LIMIT (if user specifies a number like "top 5", "first 3", "10 markets", extract that number. If not specified, return "ALL")
4. STRATEGY (SQL or BATCH or COMPARISON)
   - Use SQL for: simple queries, top/highest/lowest by volume WITHOUT semantic filtering
   - Use BATCH for: semantic search, people/entities, abstract concepts, specific subcategories within a domain
   - Use COMPARISON for: queries comparing aggregates (avg, min, max, sum) across different categories
   - CRITICAL FOR SQL: Be PRECISE with filtering - use domain, section, subsection columns to get EXACTLY what user asks for
   - Example: "basketball" → filter by section LIKE '%Basketball%' or subsection LIKE '%NBA%'
   - Example: "crypto" → filter by section LIKE '%Cryptocurrency%' or title LIKE '%crypto%'
   - Example: "NFL" → filter by section LIKE '%NFL%' or section LIKE '%Football%'
   - DO NOT return broad category results when user asks for specific subcategory
   - For COMPARISON strategy: provide multiple SQL queries, one for each category being compared
   - CRITICAL FOR COMPARISON: When aggregating top N (e.g., "avg of top 10"), use subquery:
     * Example: SELECT AVG(liquidity) FROM (SELECT liquidity FROM events WHERE domain='Finance' ORDER BY volume DESC LIMIT 10)
     * This gets top 10 by volume, THEN calculates average
5. DOMAIN_FILTER (for BATCH strategy - which domains to search)
   - Be INCLUSIVE to avoid missing results - domain filtering reduces load, not meant to be precise
   - ALWAYS include domain 7 (Miscellaneous) as it's a catch-all for various topics
   - Entertainment content (singers, actors, movies, music, celebrities) → Domain 4 (Entertainment & Culture), Miscellaneous (7)
   - Example: "interest rates" → Finance (3), Miscellaneous (7)
   - Example: "trump" → Politics (2), Miscellaneous (7)
   - Example: "government shutdown" → Politics (2), Miscellaneous (7)
   - Example: "singers" → Entertainment & Culture (4), Miscellaneous (7)
   - Example: "Taylor Swift" → Entertainment & Culture (4), Miscellaneous (7)
   - Example: "AI" → Technology (6), Miscellaneous (7)
   - If broad/unclear → ALL
6. REQUIRED_COLUMNS (for SQL queries only - BATCH always uses id+title+domain)
   Available: id, title, slug, domain, section, subsection, description, volume, liquidity, outcome_prices
   IMPORTANT: Always include 'slug' for generating market URLs in SQL queries

Response format:
INTENT: <intent description>
FILTERS: <filters or NONE>
SORTING: <sorting or NONE>

OUTPUT_FORMAT: <what to include in output>

USER_LIMIT: <number if user specifies "top 5", "first 3", "10 markets", etc., or ALL if not specified>

STRATEGY: SQL or BATCH or COMPARISON
SQL_QUERY: <if SQL, provide query WITHOUT LIMIT - we fetch all, display top 50>
BATCH_REASON: <if BATCH, provide reason here>
COMPARISON_QUERIES: <if COMPARISON, provide category names and SQL queries in format: CATEGORY1:query1|CATEGORY2:query2>

DOMAIN_FILTER: <comma-separated domain numbers (1-7) or ALL>

REQUIRED_COLUMNS: <comma-separated, minimal set>

Your response:"""

            result = self._call_gemini(combined_prompt, "Query Analysis")

            # Parse the combined response
            intent_lines = []
            output_format = ""
            strategy = "batch"
            sql_query = None
            batch_reason = None
            comparison_queries = None
            required_columns = ['id', 'title']
            domain_filter = None
            user_limit = None

            for line in result.split('\n'):
                line = line.strip()
                if line.startswith('INTENT:') or line.startswith('FILTERS:') or line.startswith('SORTING:'):
                    intent_lines.append(line)
                elif line.startswith('OUTPUT_FORMAT:'):
                    output_format = line.replace('OUTPUT_FORMAT:', '').strip()
                elif line.startswith('USER_LIMIT:'):
                    limit_str = line.replace('USER_LIMIT:', '').strip().upper()
                    if limit_str != 'ALL' and limit_str.isdigit():
                        user_limit = int(limit_str)
                elif line.startswith('STRATEGY:'):
                    strategy_val = line.replace('STRATEGY:', '').strip().upper()
                    if 'COMPARISON' in strategy_val:
                        strategy = 'comparison'
                    elif 'SQL' in strategy_val:
                        strategy = 'sql'
                    elif 'BATCH' in strategy_val:
                        strategy = 'batch'
                elif line.startswith('SQL_QUERY:'):
                    sql_query = line.replace('SQL_QUERY:', '').strip()
                elif line.startswith('BATCH_REASON:'):
                    batch_reason = line.replace('BATCH_REASON:', '').strip()
                elif line.startswith('COMPARISON_QUERIES:'):
                    comparison_queries = line.replace('COMPARISON_QUERIES:', '').strip()
                elif line.startswith('DOMAIN_FILTER:'):
                    domain_str = line.replace('DOMAIN_FILTER:', '').strip().upper()
                    if domain_str != 'ALL':
                        # Parse comma-separated domain numbers
                        domain_filter = [int(d.strip()) for d in domain_str.split(',') if d.strip().isdigit()]
                elif line.startswith('REQUIRED_COLUMNS:'):
                    cols_str = line.replace('REQUIRED_COLUMNS:', '').strip()
                    required_columns = [c.strip() for c in cols_str.split(',') if c.strip()]

            intent = '\n'.join(intent_lines) if intent_lines else f"INTENT: {user_query}"
            output_format = output_format if output_format else "Include relevant information"

            # CRITICAL: Always ensure 'id' is in required_columns (needed for matching)
            if 'id' not in required_columns:
                required_columns.insert(0, 'id')
            # CRITICAL: Always ensure 'title' is in required_columns (needed for semantic matching)
            if 'title' not in required_columns:
                required_columns.insert(1, 'title')

            return {
                'intent': intent,
                'output_format': output_format,
                'strategy': strategy,
                'sql_query': sql_query,
                'batch_reason': batch_reason,
                'comparison_queries': comparison_queries,
                'required_columns': required_columns,
                'domain_filter': domain_filter,
                'user_limit': user_limit
            }

        except Exception as e:
            print(f"Combined analysis error: {e}")
            return {
                'intent': f"INTENT: {user_query}",
                'output_format': "Include relevant information",
                'strategy': 'batch',
                'sql_query': None,
                'batch_reason': 'Error in analysis',
                'comparison_queries': None,
                'required_columns': ['id', 'title'],
                'domain_filter': None,
                'user_limit': None
            }

        except Exception as e:
            print(f"Strategy decision error: {e}")
            return ('batch', None, 'Error in decision, defaulting to batch')
    
    def execute_sql_query(self, sql_query, user_query, intent, output_format, user_limit=None):
        """Execute SQL query and format results."""
        try:
            # Safety check - only allow SELECT
            if not sql_query.strip().upper().startswith('SELECT'):
                return "Error: Only SELECT queries are allowed for safety."

            # Remove any LIMIT clause - we fetch all and display top 50
            sql_upper = sql_query.upper()
            if 'LIMIT' in sql_upper:
                limit_pos = sql_upper.find('LIMIT')
                # Find the end of LIMIT clause (usually a number or semicolon)
                rest = sql_query[limit_pos:]
                # Remove LIMIT and any following number
                import re
                sql_query = sql_query[:limit_pos] + re.sub(r'LIMIT\s+\d+\s*;?', '', rest, flags=re.IGNORECASE)
                print(f"Removed LIMIT clause from SQL query")

            # Enforce active events filter unless explicitly asking for inactive
            if 'inactive' not in user_query.lower() and 'is_active' not in sql_query.lower():
                # Inject is_active=1 filter
                sql_upper = sql_query.upper()
                if 'WHERE' in sql_upper:
                    # Add to existing WHERE clause
                    where_pos = sql_upper.find('WHERE')
                    sql_query = sql_query[:where_pos+5] + ' is_active=1 AND' + sql_query[where_pos+5:]
                elif 'ORDER BY' in sql_upper:
                    # Insert before ORDER BY
                    order_pos = sql_upper.find('ORDER BY')
                    sql_query = sql_query[:order_pos] + ' WHERE is_active=1 ' + sql_query[order_pos:]
                elif 'LIMIT' in sql_upper:
                    # Insert before LIMIT
                    limit_pos = sql_upper.find('LIMIT')
                    sql_query = sql_query[:limit_pos] + ' WHERE is_active=1 ' + sql_query[limit_pos:]
                else:
                    # Add at the end
                    sql_query = sql_query.rstrip(';') + ' WHERE is_active=1'
            
            # Enforce volume sorting if no ORDER BY specified
            sql_upper = sql_query.upper()
            if 'ORDER BY' not in sql_upper:
                if 'LIMIT' in sql_upper:
                    limit_pos = sql_upper.find('LIMIT')
                    sql_query = sql_query[:limit_pos] + ' ORDER BY volume DESC ' + sql_query[limit_pos:]
                else:
                    sql_query = sql_query.rstrip(';') + ' ORDER BY volume DESC'
            
            with ReadTracker():
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()

                cursor.execute(sql_query)
                results = cursor.fetchall()
                column_names = [desc[0] for desc in cursor.description]
                conn.close()

            self._log("info", f"📊 SQL returned {len(results)} results")

            # If < 10 results (including 0), check if query is semantic or a simple data query
            if len(results) < 10:
                # Check if this is a simple "top/highest/lowest by X" query
                query_lower = user_query.lower()
                is_simple_data_query = any(word in query_lower for word in ['top ', 'highest ', 'lowest ', 'most ', 'least ', 'first ', 'last '])

                if is_simple_data_query and len(results) > 0:
                    # For simple data queries with some results, return SQL results as-is
                    print(f"Simple data query detected - returning {len(results)} SQL results")
                else:
                    # For semantic queries OR when 0 results, use batch processing
                    print(f"Only {len(results)} SQL results - discarding and running full batch processing for semantic search")
                    return self.batch_process_events(user_query, intent, output_format, domain_filter=self._cached_domain_filter, user_limit=user_limit)

            # If >= 10 results, return SQL results directly
            # Apply user-specified limit or default to configured limit
            total_results = len(results)
            display_limit = user_limit if user_limit else DEFAULT_DISPLAY_LIMIT
            display_results = results[:display_limit]

            # Format results for display
            formatted_results = []
            structured_results = []
            for row in display_results:
                row_dict = dict(zip(column_names, row))
                formatted_results.append(row_dict)
                structured = self._structured_from_mapping(row_dict, strategy='sql')
                if structured:
                    structured_results.append(structured)
            self._record_structured_results(structured_results)

            # Format directly without Gemini call to avoid token limits
            output_lines = []
            if total_results > display_limit:
                output_lines.append(f"Found {total_results} markets (showing top {display_limit}):\n")
            else:
                output_lines.append(f"Found {total_results} market{'s' if total_results != 1 else ''}:\n")

            for i, result in enumerate(formatted_results, 1):
                line = f"{i}. **{result.get('title', 'Unknown')}**"
                if 'volume' in result and result['volume']:
                    line += f"\n   - Volume: ${result['volume']:,.0f}"
                if 'liquidity' in result and result['liquidity']:
                    line += f"\n   - Liquidity: ${result['liquidity']:,.2f}"
                if 'domain' in result and result['domain']:
                    line += f"\n   - Category: {result['domain']}"
                if 'outcome_prices' in result and result['outcome_prices'] and result['outcome_prices'] != '[]':
                    line += f"\n   - Outcome Prices: {result['outcome_prices']}"

                # Always show URL (use slug if available, otherwise use ID)
                if 'slug' in result and result['slug']:
                    line += f"\n   - 🔗 Link: https://polymarket.com/event/{result['slug']}"
                elif 'id' in result and result['id']:
                    line += f"\n   - 🔗 Link: https://polymarket.com/event/{result['id']}"

                output_lines.append(line)

            return '\n\n'.join(output_lines)
            
        except Exception as e:
            print(f"SQL execution error: {e}")
            self._record_structured_results([])
            return f"Error executing query: {str(e)}. Falling back to batch processing."

    def execute_comparison_queries(self, comparison_queries, user_query, intent, output_format, user_limit=None):
        """Execute multiple SQL queries for comparison and aggregate results."""
        try:
            self._record_structured_results([])
            if not comparison_queries:
                return "Error: No comparison queries provided"

            # Parse format: "CATEGORY1:query1|CATEGORY2:query2"
            category_queries = []
            for pair in comparison_queries.split('|'):
                if ':' not in pair:
                    continue
                parts = pair.split(':', 1)
                if len(parts) == 2:
                    category = parts[0].strip()
                    query = parts[1].strip()
                    category_queries.append((category, query))

            if not category_queries:
                return "Error: Could not parse comparison queries"

            print(f"Executing {len(category_queries)} comparison queries...")

            # Execute each query and collect results
            results_by_category = {}
            for category, sql_query in category_queries:
                # Remove LIMIT clauses
                sql_upper = sql_query.upper()
                if 'LIMIT' in sql_upper:
                    limit_pos = sql_upper.find('LIMIT')
                    rest = sql_query[limit_pos:]
                    import re
                    sql_query = sql_query[:limit_pos] + re.sub(r'LIMIT\s+\d+\s*;?', '', rest, flags=re.IGNORECASE)

                # Apply user limit if specified
                if user_limit:
                    sql_query = sql_query.rstrip(';') + f' LIMIT {user_limit}'

                # Execute query
                with ReadTracker():
                    conn = sqlite3.connect(self.db_path)
                    cursor = conn.cursor()
                    print(f"  {category}: {sql_query}")
                    cursor.execute(sql_query)
                    rows = cursor.fetchall()
                    column_names = [desc[0] for desc in cursor.description]
                    conn.close()

                # Store results with column names
                results_by_category[category] = {
                    'rows': rows,
                    'columns': column_names
                }
                print(f"  {category}: {len(rows)} results")

            # Ask Gemini to format the comparison results nicely
            comparison_data = {}
            for category, data in results_by_category.items():
                rows = data['rows']
                columns = data['columns']
                comparison_data[category] = {
                    'columns': columns,
                    'values': [[str(v) if v is not None else 'NULL' for v in row] for row in rows[:10]]
                }

            formatting_prompt = f"""Format this comparison data into a clear, concise response for the user.

USER QUERY: {user_query}

COMPARISON RESULTS:
{json.dumps(comparison_data, indent=2)}

INSTRUCTIONS:
- Present the comparison in a clear, easy-to-read format
- For aggregate values (AVG, MIN, MAX, SUM, COUNT), show as a single summary line per category
- For regular results, show as a brief list
- Use markdown formatting (**bold** for headers)
- Keep it concise - user wants a quick comparison
- If aggregating financial values (liquidity, volume), format with $ and commas

Response:"""

            return self._call_gemini(formatting_prompt, "Comparison Formatting")

        except Exception as e:
            print(f"Comparison execution error: {e}")
            return f"Error executing comparison: {str(e)}"

    def _identify_relevant_categories(self, user_query):
        """Use Gemini to identify relevant hierarchical categories for filtering."""
        category_schema = """
1. Sports
   1.1. American Football (NFL) | 1.2. Basketball (NBA) | 1.3. Soccer | 1.4. Baseball (MLB)
   1.5. Combat Sports | 1.6. Tennis | 1.7. Motorsports | 1.8. College Sports | 1.9. Other Sports

2. Politics
   2.1. US Politics | 2.2. International Politics

3. Finance
   3.1. Macroeconomics | 3.2. Cryptocurrency | 3.3. Traditional Markets

4. Entertainment & Culture
   4.1. Movies | 4.2. Awards & Ceremonies | 4.3. Celebrities & Public Figures
   4.4. Music | 4.5. Television

5. Geopolitics & World Events
   5.1. International Relations | 5.2. Conflict & Security | 5.3. Public Health
   5.4. Environment & Disasters

6. Technology
   6.1. Artificial Intelligence | 6.2. Social Media | 6.3. Space Exploration

7. Miscellaneous
   7.1. Legal & Court Cases | 7.2. Science & Discovery | 7.3. General Events
"""
        
        try:
            prompt = f"""Identify which hierarchical categories are relevant for this query.

USER QUERY: {user_query}

CATEGORY SCHEMA:
{category_schema}

Instructions:
- List ALL relevant domain numbers that could contain matching events (e.g., "1" for Sports, "2" for Politics)
- Be INCLUSIVE - if query could match multiple domains, list them all
- If uncertain or query is broad, return "ALL"

Respond with ONLY comma-separated domain numbers or "ALL":
Example: "1,2" or "3" or "ALL"

Domain numbers:"""
            
            response = self.model.generate_content(prompt)
            result = response.text.strip().upper()
            
            if result == "ALL" or not result:
                return None  # No filtering
            
            # Parse domain numbers
            domain_numbers = []
            for part in result.replace("DOMAIN NUMBERS:", "").split(','):
                part = part.strip()
                if part.isdigit():
                    domain_numbers.append(int(part))
            
            return domain_numbers if domain_numbers else None
            
        except Exception as e:
            print(f"Category identification error: {e}")
            return None  # No filtering on error

    def _identify_required_columns(self, user_query, intent):
        """Ask Gemini which columns are needed to evaluate this query."""
        try:
            available_columns = """
Available columns:
- id (always required for matching)
- title (event title/question)
- domain (category like Politics, Sports, Finance)
- section (subcategory like US Politics, NFL)
- subsection (specific type like Elections, Game Outcome)
- volume (trading volume in USD)
- liquidity (market liquidity)
- outcome_prices (current prices as JSON array)
"""

            prompt = f"""Given this user query, which columns are NECESSARY to evaluate semantic matches?

USER QUERY: {user_query}
INTENT: {intent}

{available_columns}

IMPORTANT: Only include columns that are ESSENTIAL for matching. More columns = more tokens = slower.
- 'id' and 'title' are always required
- Include 'domain'/'section'/'subsection' only if query is category-specific
- Include 'volume' only if query asks about volume/trading/liquidity
- Include 'outcome_prices' only if query asks about prices/odds

Respond with ONLY comma-separated column names.
Example: "id,title" or "id,title,domain,volume"

Required columns:"""

            response = self.model.generate_content(prompt)
            columns_str = response.text.strip()
            columns = [c.strip() for c in columns_str.split(',') if c.strip()]

            # Always ensure id and title are included
            if 'id' not in columns:
                columns.insert(0, 'id')
            if 'title' not in columns:
                columns.insert(1, 'title')

            print(f"Required columns for query: {columns}")
            return columns

        except Exception as e:
            print(f"Column identification error: {e}")
            return ['id', 'title']  # Default to minimal

    def batch_process_events(self, user_query, intent, output_format, domain_filter=None, batch_size=1000, max_batches=10, user_limit=None):
        """Process events in batches using Gemini for semantic understanding - with optional domain filtering."""
        try:
            # Fetch active markets with optional domain filtering
            with ReadTracker():
                query = self.db.session.query(Event).filter(Event.is_active == True)

                # Apply domain filtering if specified
                if domain_filter:
                    # Map domain numbers to human-readable domain names
                    domain_map = {
                        1: 'Sports',
                        2: 'Politics',
                        3: 'Finance',
                        4: 'Entertainment & Culture',
                        5: 'Geopolitics & World Events',
                        6: 'Technology',
                        7: 'Miscellaneous'
                    }
                    domain_names = [domain_map.get(d) for d in domain_filter if d in domain_map]
                    if domain_names:
                        existing_domains = {
                            row[0]
                            for row in self.db.session.query(Event.domain).distinct()
                            if row[0]
                        }
                        matching_domains = [d for d in domain_names if d in existing_domains]

                        if matching_domains:
                            query = query.filter(Event.domain.in_(matching_domains))
                            print(f"Domain filtering: {matching_domains}")
                        else:
                            print("Skipping domain filter: no matching domain metadata found in events table")

                all_events = query.order_by(Event.volume.desc()).all()

            if not all_events:
                self._record_structured_results([])
                return "No active events found."

            # Step 3: Calculate optimal batch size to limit to max 10 batches
            total_events = len(all_events)
            optimal_batch_size = max(batch_size, (total_events + max_batches - 1) // max_batches)
            actual_batches = min(max_batches, (total_events + optimal_batch_size - 1) // optimal_batch_size)

            print(f"Batch processing {total_events} active events in {actual_batches} batches of ~{optimal_batch_size}")

            # Prepare all batches first
            batches_to_process = []
            for i in range(0, len(all_events), optimal_batch_size):
                batch = all_events[i:i + optimal_batch_size]
                batch_num = (i // optimal_batch_size) + 1

                if batch_num > max_batches:
                    break  # Stop after max_batches

                # Create batch data with id, title, domain for context
                # NOTE: Description removed to reduce token usage and stay within API limits
                batch_data = []
                for e in batch:
                    batch_data.append({
                        'id': str(e.id),
                        'title': e.title,
                        'domain': e.domain or ''
                    })

                batches_to_process.append((batch_num, batch, batch_data))

            # Process all batches in parallel
            self._log("info", f"🔄 Processing {len(batches_to_process)} batches ({total_events} events total)...")
            all_matches = []
            seen_event_ids = set()  # Track event IDs to avoid duplicates
            batch_errors = []  # Track API errors

            def process_single_batch(batch_info):
                """Process a single batch and return results."""
                batch_num, batch, batch_data = batch_info

                # Ask Gemini to find relevant events in this batch with relevance scores
                batch_prompt = f"""
You are an event relationship evaluator.

USER QUERY: {user_query}
USER INTENT: {intent}

BATCH {batch_num} of events to evaluate (each with id, title, and domain):
{json.dumps(batch_data, indent=1)}

YOUR TASK:

1. INTERPRET THE INTENT:
   Understand what the user is asking for. The phrasing may vary:
   - "related events" → find events connected to the query
   - "affected by" → find events influenced or impacted by the query
   - "not affected by" → find events unaffected by the query
   - "inversely related" → find events with opposite or negative relationship
   - Domain-filtered (e.g., "in Finance", "politics only", "Sports markets") → restrict to that domain

2. DOMAIN REASONING AND MAPPING:
   - Available main domains: Sports, Politics, Finance, Entertainment & Culture, Geopolitics & World Events, Technology, Miscellaneous.
   - If the query mentions a subcategory, synonym, or related keyword (e.g., "singer", "movie", "actor"), map it to the closest main domain automatically.
   - If no domain is mentioned, evaluate across all domains.
   - Examples:
       "Singer events" → Entertainment & Culture
       "Football outcomes" → Sports
       "Fed rate changes" → Finance
       "Election impact from inflation" → Politics

3. CROSS-DOMAIN LOGIC:
   - If the query includes a cause or trigger from one domain (e.g., Finance: "Fed rates")
     and requests events in a different domain (e.g., Politics: "political events"):
       - Treat the *cause domain* as the source of impact.
       - Treat the *target domain* as the set of events to evaluate.
       - Evaluate how the cause could influence or relate to events in the target domain.

4. APPLY DOMAIN FILTERING:
   - Filter events strictly by the *target domain* determined above, **but always include events from Miscellaneous**.
   - If no domain is specified, evaluate all events normally (including Miscellaneous).

5. ASSIGN RELEVANCE SCORE (0–100):
   - 100: Exactly the same topic/question.
   - 95–99: Direct causal or dependent relationship.
   - 90–94: Strong indirect economic, strategic, or policy link.
   - 80–89: Related through shared entity, actor, or contextual driver.
   - 70–79: Same category or domain; moderate conceptual connection.
   - 60–69: Weak or tangential relation (exclude).
   - 0–59: Unrelated (exclude).

6. MINIMUM THRESHOLD:
   - Only include events scoring 70 or higher.

7. RANKING:
   - Sort included events by descending score.
   - If scores tie, prefer the one with stronger causal or directional relevance.

8. SELF-CHECK:
   - No scores below 70 appear.
   - Explanations are concise (≤15 words).
   - Output is properly ranked.

OUTPUT FORMAT:
Return a single line with events separated by "|", each in the form:
"id:score:explanation"

Example:
"123:95:ExxonMobil directly impacted by oil prices|456:87:Energy equities linked to rate policy|789:75:Commodities affect inflation politics"

If no events meet the threshold, return exactly:
"NONE"

Response:"""

                batch_matches = []
                batch_error = None

                try:
                    result = self._call_gemini(batch_prompt, f"Batch {batch_num} Semantic Matching")

                    if result.upper() != "NONE":
                        # Parse IDs with scores and reasoning (format: "id:score:reason|id:score:reason|...")
                        # Remove common prefixes (case-insensitive)
                        result_upper = result.upper()
                        if 'IDS WITH SCORES:' in result_upper:
                            idx = result_upper.index('IDS WITH SCORES:') + len('IDS WITH SCORES:')
                            result = result[idx:].strip()
                        elif 'IDS:' in result_upper:
                            idx = result_upper.index('IDS:') + len('IDS:')
                            result = result[idx:].strip()

                        id_score_reason_triples = [triple.strip() for triple in result.split('|') if triple.strip()]

                        # Get matching events with scores and reasoning
                        for triple in id_score_reason_triples:
                            try:
                                parts = triple.split(':', 2)  # Split into max 3 parts
                                if len(parts) >= 2:
                                    event_id = parts[0].strip()
                                    score = int(parts[1].strip())
                                    reasoning = parts[2].strip() if len(parts) > 2 else "relevant match"
                                else:
                                    # Fallback: if no score provided, default to 75
                                    event_id = triple.strip()
                                    score = 75
                                    reasoning = "relevant match"

                                matching_event = next((e for e in batch if str(e.id) == event_id), None)
                                if matching_event:
                                    # Store score and reasoning as attributes on the event object
                                    matching_event.relevance_score = score
                                    matching_event.relevance_reasoning = reasoning
                                    batch_matches.append((event_id, matching_event))
                            except (ValueError, AttributeError) as parse_error:
                                print(f"Warning: Could not parse '{triple}': {parse_error}")
                                continue
                except Exception as e:
                    error_msg = str(e)
                    print(f"Batch {batch_num} error: {error_msg}")
                    batch_error = (batch_num, error_msg)

                    # Check if it's a rate limit or quota error
                    if "quota" in error_msg.lower() or "rate" in error_msg.lower() or "429" in error_msg:
                        batch_error = (batch_num, error_msg, True)  # Flag as rate limit error

                return (batch_num, batch_matches, batch_error)

            # Execute batches in parallel using ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=min(len(batches_to_process), 4)) as executor:
                future_to_batch = {executor.submit(process_single_batch, batch_info): batch_info[0]
                                   for batch_info in batches_to_process}

                for future in as_completed(future_to_batch):
                    batch_num, batch_matches, batch_error = future.result()

                    if batch_error:
                        if len(batch_error) == 3 and batch_error[2]:  # Rate limit error
                            self._record_structured_results([])
                            return f"⚠️ **API Rate Limit Error**\n\nThe Gemini API free tier has a limit of 15 requests per minute. Please wait a moment and try again.\n\n**Error details:** {batch_error[1]}\n\n**Tip:** Upgrade your API plan for higher limits at https://ai.google.dev/gemini-api/docs/rate-limits"
                        batch_errors.append((batch_error[0], batch_error[1]))

                    # Add matches, avoiding duplicates
                    for event_id, matching_event in batch_matches:
                        if event_id not in seen_event_ids:
                            all_matches.append(matching_event)
                            seen_event_ids.add(event_id)

            # Sort matches by relevance score (highest first), then by volume for ties
            # Primary sort: relevance_score (descending)
            # Secondary sort: volume (descending) for same relevance scores
            all_matches.sort(key=lambda e: (
                getattr(e, 'relevance_score', 0),  # Primary: relevance score
                getattr(e, 'volume', 0)  # Secondary: volume for ties
            ), reverse=True)

            # Format final answer with all matches
            if not all_matches:
                # If we had errors but no matches, show the errors
                if batch_errors:
                    error_details = "\n".join([f"  - Batch {num}: {err[:100]}..." for num, err in batch_errors[:3]])
                    self._record_structured_results([])
                    return f"❌ **Error processing query**\n\n{error_details}\n\nPlease try again or simplify your query."
                self._record_structured_results([])
                return f"No relevant events found for: {user_query}"

            return self._format_final_answer(user_query, all_matches, intent, output_format, user_limit)
            
        except Exception as e:
            print(f"Batch processing error: {e}")
            self._record_structured_results([])
            return f"Error processing query: {str(e)}"
    
    def _format_final_answer(self, user_query, events, intent, output_format, user_limit=None):
        """Format the final answer with matched events."""
        # Apply user-specified limit or default to 50
        display_limit = user_limit if user_limit else DEFAULT_DISPLAY_LIMIT
        display_events = events[:display_limit]
        total_count = len(events)

        # Format directly without Gemini to ensure consistent output
        output_lines = []
        structured_results = []

        # Add header
        if total_count > display_limit:
            output_lines.append(f"Found {total_count} markets (showing top {display_limit}):\n")
        else:
            output_lines.append(f"Found {total_count} market{'s' if total_count != 1 else ''}:\n")

        # Determine how many results to show reasoning for (top 10 only)
        reasoning_limit = 10

        # Format each event
        for i, e in enumerate(display_events, 1):
            # Show relevance score and reasoning if available (from batch processing)
            # Only show reasoning for top min(20, user_limit) results
            score = getattr(e, 'relevance_score', None)
            reasoning = getattr(e, 'relevance_reasoning', None)

            if score and i <= reasoning_limit:
                # Show reasoning for top results only
                if reasoning:
                    line = f"{i}. **{e.title}** (Relevance: {score}/100 - {reasoning})"
                else:
                    line = f"{i}. **{e.title}** (Relevance: {score}/100)"
            elif score:
                # Show score only without reasoning for remaining results
                line = f"{i}. **{e.title}** (Relevance: {score}/100)"
            else:
                line = f"{i}. **{e.title}**"

            if e.volume:
                line += f"\n   - Volume: ${e.volume:,.0f}"
            if e.liquidity:
                line += f"\n   - Liquidity: ${e.liquidity:,.2f}"
            if e.outcome_prices and e.outcome_prices != '[]':
                line += f"\n   - Outcome Prices: {e.outcome_prices}"

            # Always show URL (use slug if available, otherwise use ID)
            if e.slug:
                line += f"\n   - 🔗 Link: https://polymarket.com/event/{e.slug}"
            elif e.id:
                line += f"\n   - 🔗 Link: https://polymarket.com/event/{e.id}"

            output_lines.append(line)
            structured = self._structured_from_event(e, strategy='batch')
            if structured:
                structured_results.append(structured)

        self._record_structured_results(structured_results)
        return '\n\n'.join(output_lines)
    
    def process_query(self, user_query):
        """Main query processing with intelligent strategy selection."""
        try:
            # Log query
            self._log("info", f"📥 Query: {user_query}")
            self._reset_structured_results()

            # Pre-step: Add system context to query
            contextualized_query = f"""SYSTEM CONTEXT: You are a Polymarket prediction markets chatbot with access to a database of markets/events.

CRITICAL INSTRUCTION: Unless the user explicitly asks a generic question (e.g., "what is polymarket?", "how do prediction markets work?"), you MUST query the database and return actual markets/events from it.

Examples:
- "interest rates" → Find markets about interest rates in the database
- "trump" → Find markets about Trump in the database
- "AI markets" → Find markets about AI in the database
- "what is polymarket?" → Generic question, can answer without database

USER QUERY: {user_query}"""

            # Single combined analysis (saves 3-4 API calls)
            self._log("info", "🔍 Step 1: Analyzing query strategy...")
            analysis = self.analyze_query_all_in_one(contextualized_query)

            intent = analysis['intent']
            output_format = analysis['output_format']
            strategy = analysis['strategy']
            sql_info = analysis['sql_query']
            batch_info = analysis['batch_reason']
            comparison_info = analysis['comparison_queries']
            self._cached_required_columns = analysis['required_columns']
            self._cached_domain_filter = analysis['domain_filter']
            user_limit = analysis['user_limit']

            # Log strategy decision
            if strategy == 'sql':
                self._log("info", f"✅ Strategy: SQL")
                self._log("info", f"📝 SQL Query: {sql_info}")
            elif strategy == 'batch':
                self._log("info", f"✅ Strategy: BATCH (Semantic Search)")
                self._log("info", f"💭 Reason: {batch_info}")
                if self._cached_domain_filter:
                    self._log("info", f"🏷️ Domains: {self._cached_domain_filter}")
            elif strategy == 'comparison':
                self._log("info", f"✅ Strategy: COMPARISON")
                self._log("info", f"📊 Queries: {comparison_info}")

            # Execute based on strategy
            if strategy == 'sql':
                self._log("info", "⚙️ Step 2: Executing SQL query...")
                result = self.execute_sql_query(sql_info, user_query, intent, output_format, user_limit)
                self._log("info", f"✅ SQL execution complete")
                return result
            elif strategy == 'comparison':
                self._log("info", "⚙️ Step 2: Executing comparison queries...")
                result = self.execute_comparison_queries(comparison_info, user_query, intent, output_format, user_limit)
                self._log("info", f"✅ Comparison complete")
                return result
            elif strategy == 'batch':
                self._log("info", "⚙️ Step 2: Starting batch semantic search...")
                result = self.batch_process_events(user_query, intent, output_format, domain_filter=self._cached_domain_filter, user_limit=user_limit)
                self._log("info", f"✅ Batch processing complete")
                return result
            else:
                return "Error: Unknown strategy"

        except Exception as e:
            self._log("error", f"❌ Error: {str(e)}")
            self._record_structured_results([])
            return f"I encountered an error: {str(e)}"
    
    def close(self):
        """Close database connection."""
        self.db.close()


def main():
    """Test the intelligent bot."""
    api_key = os.getenv('GEMINI_API_KEY', 'AIzaSyBeNxxwILHyuPEljDD2pDDfG2ZrOIP4-ng')
    bot = IntelligentGeminiBot(api_key)
    
    print("=" * 70)
    print("🧠 INTELLIGENT POLYMARKET CHATBOT")
    print("=" * 70)
    print("Features:")
    print("  • SQL queries for data operations (fast)")
    print("  • Batch processing for semantic queries (accurate)")
    print("  • Gemini decides the best strategy")
    print("=" * 70)
    
    # Test queries
    test_queries = [
        "Top 5 markets by volume",
        "Markets about artificial intelligence",
        "What are recent crypto markets?",
    ]
    
    for query in test_queries:
        print(f"\n{'='*70}")
        response = bot.process_query(query)
        print(f"\n💬 {query}")
        print(f"📝 {response[:300]}...")
    
    # Interactive mode
    print(f"\n{'='*70}")
    print("Interactive mode (type 'quit' to exit)")
    
    try:
        while True:
            user_input = input("\n👤 You: ").strip()
            
            if user_input.lower() in ['quit', 'exit', 'bye']:
                print("👋 Goodbye!")
                break
            
            if not user_input:
                continue
            
            response = bot.process_query(user_input)
            print(f"\n🤖 Bot: {response}")
    
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")
    finally:
        bot.close()


if __name__ == "__main__":
    main()
