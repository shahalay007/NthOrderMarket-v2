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
import re
from collections import Counter
from datetime import datetime, timedelta
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor, as_completed
import google.generativeai as genai
import requests
from database import Database, Event
from sqlalchemy import text, or_
from db_sync import ReadTracker

# Shared keyword utilities for semantic batching
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "does", "do",
    "for", "from", "how", "if", "in", "is", "it", "its", "more", "of",
    "on", "or", "than", "that", "the", "their", "them", "then", "there",
    "they", "this", "to", "was", "what", "when", "where", "which", "who",
    "will", "with", "would", "markets", "market", "affected", "top", "best",
    "highest", "lowest", "about", "show", "list", "give"
}
SHORT_KEYWORDS = {"ai", "uk", "us", "eu", "ufc", "nba", "nfl", "mlb"}
DEFAULT_DISPLAY_LIMIT = 20
DOMAIN_NUMBER_MAP = {
    1: "Sports: Soccer (Football)",
    2: "Sports: North American Leagues (NHL, MLB, NFL, NBA)",
    3: "Sports: Combat & eSports (Gaming, Fighting, Cricket)",
    4: "Cryptocurrency: Price (Immediate/Daily)",
    5: "Cryptocurrency: Products & Futures (Tokens, ETFs, Price Targets)",
    6: "Politics: U.S. Domestic & Legal",
    7: "Politics: Global & Military Conflict",
    8: "Technology & Business (Product Releases, AI, IPOs)",
    9: "Media & Entertainment (Awards, Celebs, Content Views)",
    10: "Finance & Economics (Earnings, Macro Indicators)",
    11: "Miscellaneous",
}

class IntelligentGeminiBot:
    def __init__(self, api_key, db_path='polymarket_read.db', log_callback=None, perplexity_api_key=None):
        """Initialize intelligent Gemini chatbot with read-only database."""
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel('gemini-1.5-flash')
        self.db = Database(db_path=db_path)
        self.db_path = db_path
        self.log_callback = log_callback  # Callback for logging to Flask
        self.perplexity_api_key = perplexity_api_key or os.getenv('PERPLEXITY_API_KEY')

        # Store last structured results for downstream consumers (e.g., UI tables)
        self.last_structured_results = []

        # Cache for stats
        self._stats_cache = None
        self._stats_cache_time = None
        self._cache_ttl = timedelta(minutes=5)
        self._cached_perplexity_context = None
        self._cached_perplexity_queries = None
        self._cached_domain_filter = None
        self._cached_required_columns = None
        self._last_thinking_trace = None
        self._platform_filter = 'POLYMARKET'

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
        """Clear cached structured results before processing a new query."""
        self.last_structured_results = []

    def _record_structured_results(self, events):
        """Persist structured results for downstream consumers."""
        self.last_structured_results = events or []

    def get_structured_results(self):
        """Return a shallow copy of the last structured results."""
        return list(self.last_structured_results)

    def get_thinking_trace(self):
        """Expose the most recent Perplexity thinking trace, if available."""
        return self._last_thinking_trace

    def get_perplexity_queries(self):
        """Return cached Perplexity subqueries, if any."""
        return list(self._cached_perplexity_queries) if self._cached_perplexity_queries else []

    def get_perplexity_context_preview(self, max_lines=5):
        """Return a short preview of cached Perplexity context."""
        if not self._cached_perplexity_context:
            return None
        lines = [line.strip() for line in self._cached_perplexity_context.splitlines() if line.strip()]
        if not lines:
            return None
        preview = lines[:max_lines]
        if len(lines) > max_lines:
            preview.append("...")
        return "\n".join(preview)

    def get_platform_filter(self):
        """Return the platform preference from the latest analysis."""
        return getattr(self, '_platform_filter', 'BOTH')

    @staticmethod
    def _detect_metric_field(user_query):
        """Infer the metric column (volume/liquidity/open_interest) from the query."""
        if not user_query:
            return 'volume'
        lowered = user_query.lower()
        if 'liquidity' in lowered:
            return 'liquidity'
        if 'open interest' in lowered or 'open-interest' in lowered or 'oi' in lowered:
            return 'open_interest'
        return 'volume'

    @staticmethod
    def _is_simple_metric_query(user_query):
        """Detect simple ranking/filtering queries that don't need external context."""
        if not user_query:
            return False
        query = user_query.lower()
        
        # Check for ranking keywords
        rank_tokens = ["top", "highest", "biggest", "largest", "most", "first", "best", "top 10", "top10", "top-five", "top5", "top 5", "top 20", "top 50"]
        rank_hit = any(token in query for token in rank_tokens)
        
        # Check for metric keywords
        metric_tokens = ["volume", "liquidity", "open interest", "oi", "trade volume", "volume traded", "trading volume"]
        metric_hit = any(token in query for token in metric_tokens)
        
        # Check for simple "by" constructions (e.g., "markets by volume")
        by_construction = "by" in query and any(metric in query for metric in ["volume", "liquidity", "open interest"])
        
        # Check for simple market queries without specific topics
        simple_market_queries = any(word in query for word in ["markets", "events", "prediction markets"]) and not any(topic in query for topic in ["about", "related to", "involving", "for", "on"])
        
        return (rank_hit and metric_hit) or by_construction or (simple_market_queries and metric_hit)

    @staticmethod
    def _normalize_numeric(value):
        """Convert value to float for consistent downstream usage."""
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
        """Build a Polymarket URL from slug/id data."""
        if slug:
            return f'https://polymarket.com/event/{slug}'
        if event_id:
            return f'https://polymarket.com/event/{event_id}'
        return None

    def _map_domain_filter(self, domain_filter):
        """Translate numeric domain filters into domain labels present in the DB."""
        if not domain_filter:
            return []
        mapped = []
        for code in domain_filter:
            name = DOMAIN_NUMBER_MAP.get(code)
            if name:
                mapped.append(name)
        return mapped

    def _sql_prefilter_events(self, keywords=None, phrases=None, domain_filter=None, limit=400, order_field='volume'):
        """Use SQL to prefilter markets by domain and optional keywords before Gemini scoring."""
        keywords = keywords or []
        phrases = phrases or []
        has_domain = bool(domain_filter)
        has_keywords = bool(keywords or phrases)
        if not has_domain and not has_keywords:
            return []

        with ReadTracker():
            query = self.db.session.query(Event).filter(Event.is_active == True)

            if has_domain:
                domain_names = self._map_domain_filter(domain_filter)
                if domain_names:
                    query = query.filter(Event.domain.in_(domain_names))

            if has_keywords:
                keyword_conditions = []
                for token in keywords:
                    pattern = f"%{token}%"
                    keyword_conditions.extend([
                        Event.title.ilike(pattern),
                        Event.slug.ilike(pattern),
                        Event.domain.ilike(pattern),
                        Event.section.ilike(pattern),
                        Event.subsection.ilike(pattern),
                    ])
                for phrase in phrases:
                    pattern = f"%{phrase}%"
                    keyword_conditions.append(Event.title.ilike(pattern))
                if keyword_conditions:
                    query = query.filter(or_(*keyword_conditions))

            order_column = getattr(Event, order_field, Event.volume)
            events = query.order_by(order_column.desc(), Event.volume.desc()).limit(limit).all()

        if events:
            self._log('info', f'🎯 SQL prefilter matched {len(events)} candidates')
        else:
            self._log('info', '🎯 SQL prefilter returned no candidates')
        return events

    def _structured_from_mapping(self, mapping, strategy='sql', relevance=None, reasoning=None):
        """Create a normalized structured event dict from a mapping row."""
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
            'relevance': relevance,
            'reasoning': reasoning,
            'url': self._build_market_url(slug, event_id),
            'strategy': strategy
        }

    def _structured_from_event(self, event, strategy='batch'):
        """Create structured event dict from ORM Event."""
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
            'relevance': relevance,
            'reasoning': reasoning,
            'url': self._build_market_url(getattr(event, 'slug', None), getattr(event, 'id', None)),
            'strategy': strategy
        }

    def _fetch_perplexity_context(self, queries, max_results=5):
        """Retrieve contextual snippets from Perplexity for one or more queries."""
        if not self.perplexity_api_key:
            return None

        if isinstance(queries, str):
            queries = [queries]

        if not queries:
            return None

        normalized_queries = [q.strip() for q in queries if q and q.strip()]
        if not normalized_queries:
            return None

        url = "https://api.perplexity.ai/search"
        headers = {
            "Authorization": f"Bearer {self.perplexity_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "query": normalized_queries if len(normalized_queries) > 1 else normalized_queries[0],
            "max_results": max_results,
            "num_results": max_results,
            "include_answer": True,
        }

        try:
            response = requests.post(url, headers=headers, json=payload, timeout=10)
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as request_error:
            self._log('error', f'Perplexity search failed: {request_error}')
            return None
        except ValueError:
            self._log('error', 'Perplexity search returned invalid JSON response')
            return None

        def _extract_title(result):
            title = result.get('title') or result.get('source') or result.get('url')
            if isinstance(title, dict):
                title = title.get('name') or title.get('title')
            return title

        def _extract_snippet(result):
            snippet = result.get('snippet') or result.get('text') or result.get('content')
            if snippet:
                return snippet.strip()
            return None

        context_bits = []

        # Capture combined or per-query answers if provided
        answers = data.get('answers') or data.get('answer')
        if isinstance(answers, list):
            for idx, answer in enumerate(answers):
                if answer:
                    prefix = normalized_queries[idx] if idx < len(normalized_queries) else f"Query {idx + 1}"
                    context_bits.append(f"Summary ({prefix}): {answer.strip()}")
        elif isinstance(answers, str):
            context_bits.append(f"Summary: {answers.strip()}")

        raw_results = data.get('results') or data.get('top_results') or []

        # Normalize into dict mapping query label to list of result dicts
        per_query_results = {}
        if isinstance(raw_results, list):
            if raw_results and all(isinstance(item, list) for item in raw_results):
                for idx, query_results in enumerate(raw_results):
                    label = normalized_queries[idx] if idx < len(normalized_queries) else f"Query {idx + 1}"
                    per_query_results[label] = query_results
            else:
                label = normalized_queries[0] if normalized_queries else "Query 1"
                per_query_results[label] = raw_results
        elif isinstance(raw_results, dict):
            for key, value in raw_results.items():
                if isinstance(value, list):
                    label = key
                    if key.isdigit():
                        idx = int(key) - 1
                        if 0 <= idx < len(normalized_queries):
                            label = normalized_queries[idx]
                    per_query_results[label] = value

        for label, results in per_query_results.items():
            if len(normalized_queries) > 1:
                context_bits.append(f"Query focus: {label}")
            if not isinstance(results, list):
                continue
            added = 0
            for result in results:
                if added >= max_results:
                    break
                if not isinstance(result, dict):
                    continue
                snippet = _extract_snippet(result)
                if not snippet:
                    continue
                title = _extract_title(result)
                if title:
                    context_bits.append(f"- {snippet} (Source: {title})")
                else:
                    context_bits.append(f"- {snippet}")
                added += 1

        if not context_bits:
            return None

        context_text = '\n'.join(context_bits)
        self._log('info', f"🌐 Perplexity: gathered {len(context_bits)} context lines from {len(normalized_queries)} queries")
        return context_text

    def _build_thinking_trace(self, include_context=True, context_preview_lines=3):
        """Build a human-readable trace of Perplexity queries and context."""
        if not self._cached_perplexity_queries:
            return None

        lines = ["🤔 Thinking through the query", "Perplexity sub-queries:"]
        for idx, query in enumerate(self._cached_perplexity_queries, 1):
            lines.append(f"  {idx}. {query}")

        if include_context and self._cached_perplexity_context:
            context_lines = [line.strip() for line in self._cached_perplexity_context.splitlines() if line.strip()]
            if context_lines:
                lines.append("Context highlights:")
                for snippet in context_lines[:context_preview_lines]:
                    lines.append(f"  - {snippet}")
                if len(context_lines) > context_preview_lines:
                    lines.append("  - …")

        return "\n".join(lines)

    def _update_thinking_trace(self):
        """Refresh the cached thinking trace after fetching Perplexity context."""
        self._last_thinking_trace = self._build_thinking_trace()

    def _generate_perplexity_subqueries(self, user_query, intent=None, min_queries=3, max_queries=5):
        """Generate diversified subqueries to enrich Perplexity lookups."""
        min_queries = max(1, min_queries)
        max_queries = max(min_queries, max_queries)

        seed_queries = []
        if user_query and user_query.strip():
            seed_queries.append(user_query.strip())

        prompt = f"""Decompose the following prediction-market user request into {min_queries}-{max_queries} diverse news-style subqueries.
User query: {user_query}
Intent summary: {intent or 'unknown'}

Guidelines:
- Prioritize gathering recent news, developments, or factual context about the key events, entities, or nouns in the query.
- Capture different entities, catalysts, and time horizons relevant to the prediction context.
- Keep each subquery between 5 and 12 words.
- Include at least one subquery tying the subject back to Polymarket, betting markets, or odds if relevant.
- Output ONLY a JSON array of strings, no prose.
"""

        generated_queries = []
        try:
            response = self.model.generate_content(prompt)
            raw_text = response.text.strip()

            def _extract_json_array(text):
                try:
                    parsed = json.loads(text)
                    if isinstance(parsed, list):
                        return parsed
                except json.JSONDecodeError:
                    pass
                match = re.search(r"\[[\s\S]*\]", text)
                if match:
                    try:
                        parsed = json.loads(match.group(0))
                        if isinstance(parsed, list):
                            return parsed
                    except json.JSONDecodeError:
                        return None
                return None

            parsed_queries = _extract_json_array(raw_text)
            if parsed_queries:
                generated_queries = [q.strip() for q in parsed_queries if isinstance(q, str) and q.strip()]
        except Exception as err:
            self._log('error', f'Perplexity subquery generation failed: {err}')

        if not generated_queries:
            keywords, phrases = self._extract_query_keywords(user_query, max_keywords=8)
            generated_queries.extend([f"{phrase} latest developments" for phrase in phrases[:2]])
            generated_queries.extend([f"{kw} prediction market odds" for kw in keywords[:3]])
            if intent:
                generated_queries.append(intent)

        combined = seed_queries + generated_queries
        deduped = []
        seen = set()
        for query in combined:
            normalized = query.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(query)
            if len(deduped) >= max_queries:
                break

        if len(deduped) < min_queries:
            # Backfill with generic drill-downs derived from keywords
            keywords, _ = self._extract_query_keywords(user_query, max_keywords=6)
            for kw in keywords:
                filler = f"{kw} background context"
                if filler.lower() not in seen:
                    deduped.append(filler)
                    seen.add(filler.lower())
                if len(deduped) >= min_queries:
                    break

        return deduped

    def _ensure_perplexity_context(self, user_query, intent=None, min_queries=3, max_queries=5):
        """Ensure perplexity context is cached for reasoning-heavy flows."""
        if self._cached_perplexity_context:
            return self._cached_perplexity_context

        subqueries = self._generate_perplexity_subqueries(user_query, intent, min_queries, max_queries)
        if not subqueries:
            subqueries = [user_query]

        context = self._fetch_perplexity_context(subqueries, max_results=5)
        if context:
            self._cached_perplexity_context = context
            self._cached_perplexity_queries = subqueries
            self._log('info', f"🌐 Perplexity subqueries: {subqueries}")
        else:
            self._cached_perplexity_queries = subqueries
        self._update_thinking_trace()
        return self._cached_perplexity_context

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
- liquidity (INTEGER) - Total market liquidity
- liquidity_num (INTEGER) - Numeric liquidity
- liquidity_clob (INTEGER) - CLOB liquidity
- open_interest (INTEGER) - Open interest
- created_at (DATETIME) - Creation timestamp
- updated_at (DATETIME) - Last update timestamp
- last_synced (DATETIME) - Last sync timestamp

CRITICAL: Do NOT include price-related columns like 'outcome_prices', 'last_trade_price', 'best_bid', 'best_ask', or any other columns not listed above. They are excluded from queries.

Common query patterns:
- Top volume: SELECT id, title, slug, domain, section, subsection, volume, liquidity FROM events WHERE is_active=1 ORDER BY volume DESC
- Recent: SELECT id, title, slug, domain, section, subsection, volume, liquidity FROM events WHERE is_active=1 ORDER BY updated_at DESC
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
1. Sports: Soccer (Football)
2. Sports: North American Leagues (NHL, MLB, NFL, NBA)
3. Sports: Combat & eSports (Gaming, Fighting, Cricket)
4. Cryptocurrency: Price (Immediate/Daily)
5. Cryptocurrency: Products & Futures (Tokens, ETFs, Price Targets)
6. Politics: U.S. Domestic & Legal
7. Politics: Global & Military Conflict
8. Technology & Business (Product Releases, AI, IPOs)
9. Media & Entertainment (Awards, Celebs, Content Views)
10. Finance & Economics (Earnings, Macro Indicators)
11. Miscellaneous

Provide the following in your response:

1. INTENT (what user wants, filters, sorting)
2. OUTPUT_FORMAT (what to show in response)
3. USER_LIMIT (if user specifies a number like "top 5", "first 3", "10 markets", extract that number. If not specified, return "ALL")
4. STRATEGY (SQL or BATCH or COMPARISON)
   - Use SQL for: simple queries, top/highest/lowest by volume WITHOUT semantic filtering
   - ALWAYS choose SQL when the user mentions ranking markets by volume/liquidity/open interest (e.g., "top 10 <topic> by volume")
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
   - ALWAYS include domain 11 (Miscellaneous) as it's a catch-all for various topics
   - Soccer clubs/leagues → Domain 1 (Sports: Soccer), Miscellaneous (11)
   - NFL / NBA / MLB / NHL → Domain 2 (Sports: North American Leagues), Miscellaneous (11)
   - MMA, esports, cricket, tennis → Domain 3 (Sports: Combat & eSports), Miscellaneous (11)
   - Bitcoin/Ethereum hourly or date-specific movement → Domain 4 (Crypto: Price), Miscellaneous (11)
   - Token launches, crypto ETFs, airdrops → Domain 5 (Crypto: Products & Futures), Miscellaneous (11)
   - U.S. elections, Congress, Supreme Court → Domain 6 (Politics: U.S. Domestic & Legal), Miscellaneous (11)
   - International conflicts, foreign elections → Domain 7 (Politics: Global & Military Conflict), Miscellaneous (11)
   - AI models, hardware launches, IPOs → Domain 8 (Technology & Business), Miscellaneous (11)
   - Movies, celebrities, streaming stats → Domain 9 (Media & Entertainment), Miscellaneous (11)
   - Earnings, GDP, CPI, recession odds → Domain 10 (Finance & Economics), Miscellaneous (11)
   - If broad/unclear → ALL
6. REQUIRED_COLUMNS (for SQL queries only - BATCH always uses id+title+domain)
   Available: id, title, slug, domain, section, subsection, description, volume, liquidity, open_interest
   DEFAULT BEHAVIOR: Always include ALL available columns for complete data display
   REQUIRED COLUMNS: id, title, slug, domain, section, subsection, volume, liquidity
   IMPORTANT: 
   - Always include 'slug' for generating market URLs
   - Always include 'domain' for categorization
   - Always include 'volume' and 'liquidity' for financial metrics
   - Do NOT include any price-related columns (outcome_prices, last_trade_price, best_bid, best_ask)

7. PLATFORM_FILTER (currently only POLYMARKET is supported)

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

DOMAIN_FILTER: <comma-separated domain numbers (1-11) or ALL>

PLATFORM_FILTER: POLYMARKET

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
            required_columns = ['id', 'title', 'slug', 'domain', 'section', 'subsection', 'volume', 'liquidity']
            domain_filter = None
            user_limit = None
            platform_filter = 'POLYMARKET'

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
                elif line.startswith('PLATFORM_FILTER:'):
                    platform_str = line.replace('PLATFORM_FILTER:', '').strip().upper()
                    if platform_str == 'POLYMARKET':
                        platform_filter = platform_str
                    else:
                        platform_filter = 'POLYMARKET'
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

            result_dict = {
                'intent': intent,
                'output_format': output_format,
                'strategy': strategy,
                'sql_query': sql_query,
                'batch_reason': batch_reason,
            'comparison_queries': comparison_queries,
            'required_columns': required_columns,
            'domain_filter': domain_filter,
                'user_limit': user_limit,
                'platform_filter': platform_filter
            }
            self._log("info", f"🎯 Platform filter: {platform_filter}")
            return result_dict

        except Exception as e:
            print(f"Combined analysis error: {e}")
            return {
                'intent': f"INTENT: {user_query}",
                'output_format': "Include relevant information",
                'strategy': 'batch',
                'sql_query': None,
                'batch_reason': 'Error in analysis',
                'comparison_queries': None,
                'required_columns': ['id', 'title', 'slug', 'domain', 'section', 'subsection', 'volume', 'liquidity'],
                'domain_filter': None,
                'user_limit': None,
                'platform_filter': 'BOTH'
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
                    if not self._cached_perplexity_context:
                        self._ensure_perplexity_context(user_query, intent)
                    return self.batch_process_events(
                        user_query,
                        intent,
                        output_format,
                        domain_filter=self._cached_domain_filter,
                        user_limit=user_limit,
                        external_context=self._cached_perplexity_context,
                    )

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

    def execute_comparison_queries(self, comparison_queries, user_query, intent, output_format, user_limit=None, external_context=None):
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

            context_section = ""
            if external_context:
                context_section = f"\nEXTERNAL CONTEXT FROM PERPLEXITY SEARCH:\n{external_context}\n"

            formatting_prompt = f"""Format this comparison data into a clear, concise response for the user.

USER QUERY: {user_query}
{context_section}

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
1. Sports: Soccer (Football)
2. Sports: North American Leagues (NHL, MLB, NFL, NBA)
3. Sports: Combat & eSports (Gaming, Fighting, Cricket)
4. Cryptocurrency: Price (Immediate/Daily)
5. Cryptocurrency: Products & Futures (Tokens, ETFs, Price Targets)
6. Politics: U.S. Domestic & Legal
7. Politics: Global & Military Conflict
8. Technology & Business (Product Releases, AI, IPOs)
9. Media & Entertainment (Awards, Celebs, Content Views)
10. Finance & Economics (Earnings, Macro Indicators)
11. Miscellaneous
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
"""

            prompt = f"""Given this user query, which columns are NECESSARY to evaluate semantic matches?

USER QUERY: {user_query}
INTENT: {intent}

{available_columns}

IMPORTANT: Only include columns that are ESSENTIAL for matching. More columns = more tokens = slower.
- 'id' and 'title' are always required
- Include 'domain'/'section'/'subsection' only if query is category-specific
- Include 'volume' only if query asks about volume/trading/liquidity
- Do NOT include any price-related columns

Respond with ONLY comma-separated column names.
Example: "id,title" or "id,title,domain,volume"

Required columns:"""

            response = self.model.generate_content(prompt)
            columns_str = response.text.strip()
            columns = [c.strip() for c in columns_str.split(',') if c.strip()]

            # Always ensure essential columns are included
            essential_columns = ['id', 'title', 'slug', 'domain', 'section', 'subsection', 'volume', 'liquidity']
            for col in essential_columns:
                if col not in columns:
                    columns.append(col)

            print(f"Required columns for query: {columns}")
            return columns

        except Exception as e:
            print(f"Column identification error: {e}")
            return ['id', 'title', 'slug', 'domain', 'section', 'subsection', 'volume', 'liquidity']  # Default to complete set

    def _extract_query_keywords(self, user_query, max_keywords=12):
        """Extract meaningful keywords and phrases from the user query."""
        if not user_query:
            return [], []

        lowered = user_query.lower()
        tokens = re.findall(r"[a-z0-9']+", lowered)
        keywords = []

        for token in tokens:
            if len(token) < 3 and token not in SHORT_KEYWORDS:
                continue
            if token in STOPWORDS:
                continue
            keywords.append(token)

        # Include frequent keywords first
        ranked_tokens = [token for token, _ in Counter(keywords).most_common(max_keywords)]

        # Build simple bi-grams for phrase matching
        phrases = []
        for i in range(len(tokens) - 1):
            first, second = tokens[i], tokens[i + 1]
            if first in STOPWORDS and second in STOPWORDS:
                continue
            phrase = f"{first} {second}"
            if len(phrase.replace(' ', '')) >= 5:
                phrases.append(phrase)

        # Deduplicate while preserving order
        def _dedupe(seq):
            seen = set()
            ordered = []
            for item in seq:
                if item and item not in seen:
                    seen.add(item)
                    ordered.append(item)
            return ordered

        ranked_tokens = _dedupe(ranked_tokens)[:max_keywords]
        phrases = _dedupe(phrases)[:max(4, max_keywords // 2)]

        return ranked_tokens, phrases

    def _prefilter_events_by_keywords(self, events, keywords, phrases, min_results=60, max_results=800):
        """Reduce the candidate set using quick keyword filters before semantic batching."""
        if not events or not keywords:
            return events

        filtered = []
        fallback_events = []
        lower_keywords = [kw.lower() for kw in keywords]
        lower_phrases = [ph.lower() for ph in phrases]

        for event in events:
            text_parts = [
                event.title or "",
                event.description or "",
                event.section or "",
                event.subsection or "",
            ]
            haystack = " ".join(text_parts).lower()
            score = 0

            for kw in lower_keywords:
                if kw and kw in haystack:
                    score += 2

            for phrase in lower_phrases:
                if phrase and phrase in haystack:
                    score += 3

            if score > 0:
                event.keyword_score = score
                filtered.append(event)
            else:
                fallback_events.append(event)

        if not filtered:
            return events

        filtered.sort(key=lambda e: (getattr(e, 'keyword_score', 0), getattr(e, 'volume', 0) or 0), reverse=True)
        trimmed = filtered[:max_results]

        if len(trimmed) < min_results and fallback_events:
            needed = min_results - len(trimmed)
            fallback_events.sort(key=lambda e: getattr(e, 'volume', 0) or 0, reverse=True)
            trimmed.extend(fallback_events[:needed])

        self._log('info', f'🔍 Keyword prefilter: kept {len(trimmed)} of {len(events)} events')
        return trimmed

    def _keyword_sql_fallback(self, keywords, phrases, limit=20):
        """Run a deterministic keyword LIKE search when semantic results are sparse."""
        if not keywords and not phrases:
            return []

        like_terms = [kw.lower() for kw in keywords]
        like_terms.extend(ph.lower() for ph in phrases)
        like_terms = [term for term in like_terms if term]

        if not like_terms:
            return []

        with ReadTracker():
            query = self.db.session.query(Event).filter(Event.is_active == True)
            like_filters = []

            for term in like_terms:
                pattern = f"%{term}%"
                like_filters.append(Event.title.ilike(pattern))
                like_filters.append(Event.description.ilike(pattern))
            if like_filters:
                query = query.filter(or_(*like_filters))

            results = query.order_by(Event.volume.desc()).limit(limit).all()

        for event in results:
            match_hits = 0
            haystack = f"{event.title or ''} {event.description or ''}".lower()
            matched_terms = []
            for term in like_terms:
                if term in haystack:
                    match_hits += 1
                    matched_terms.append(term)
            base_score = 72 + min(match_hits, 5) * 4
            event.relevance_score = min(base_score, 95)
            if matched_terms:
                event.relevance_reasoning = f"Direct keyword match on {', '.join(sorted(set(matched_terms)))}"
            else:
                event.relevance_reasoning = "Direct keyword match"

        return results

    def batch_process_events(self, user_query, intent, output_format, domain_filter=None, batch_size=200, max_batches=10, user_limit=None, external_context=None, prefetched_events=None):
        """Process events in batches using Gemini for semantic understanding."""
        try:
            # Fetch active markets with optional domain filtering
            if prefetched_events is not None:
                all_events = prefetched_events
            else:
                with ReadTracker():
                    query = self.db.session.query(Event).filter(Event.is_active == True)

                    if domain_filter:
                        mapped_domains = self._map_domain_filter(domain_filter)
                        if mapped_domains:
                            existing_domains = {
                                row[0]
                                for row in self.db.session.query(Event.domain).distinct()
                                if row[0]
                            }
                            matching_domains = [d for d in mapped_domains if d in existing_domains]

                            if matching_domains:
                                query = query.filter(Event.domain.in_(matching_domains))
                                print(f"Domain filtering: {matching_domains}")
                            else:
                                print("Skipping domain filter: no matching domain metadata found in events table")

                    all_events = query.order_by(Event.volume.desc()).all()

            if not all_events:
                self._record_structured_results([])
                return "No active events found."

            # Keyword prefilter to shrink semantic batches for entity-focused queries
            keywords, phrases = self._extract_query_keywords(user_query)
            if keywords:
                self._log('info', f"🗝️ Keywords: {keywords[:6]}")
            filtered_events = self._prefilter_events_by_keywords(
                all_events,
                keywords,
                phrases,
                min_results=100,
                max_results=batch_size * max_batches
            )
            events_for_batches = filtered_events if filtered_events else all_events

            # Step 3: Calculate batch sizing (defaults to ~200 events per batch)
            total_events = len(events_for_batches)
            optimal_batch_size = batch_size
            actual_batches = min(max_batches, (total_events + optimal_batch_size - 1) // optimal_batch_size)

            print(f"Batch processing {total_events} active events in {actual_batches} batches of ~{optimal_batch_size}")

            # Prepare all batches first
            batches_to_process = []
            for i in range(0, len(events_for_batches), optimal_batch_size):
                batch = events_for_batches[i:i + optimal_batch_size]
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
                context_section = ""
                if external_context:
                    context_section = f"\nADDITIONAL CONTEXT FROM PERPLEXITY SEARCH:\n{external_context}\n"

                batch_prompt = f"""
You are an event relationship evaluator.

USER QUERY: {user_query}
USER INTENT: {intent}
{context_section}

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
   - Available main domains:
       1. Sports: Soccer (Football)
       2. Sports: North American Leagues (NHL, MLB, NFL, NBA)
       3. Sports: Combat & eSports (Gaming, Fighting, Cricket)
       4. Cryptocurrency: Price (Immediate/Daily)
       5. Cryptocurrency: Products & Futures (Tokens, ETFs, Price Targets)
       6. Politics: U.S. Domestic & Legal
       7. Politics: Global & Military Conflict
       8. Technology & Business (Product Releases, AI, IPOs)
       9. Media & Entertainment (Awards, Celebs, Content Views)
       10. Finance & Economics (Earnings, Macro Indicators)
       11. Miscellaneous
   - Map synonyms automatically (e.g., "Premier League" → Domain 1, "Fed" → Domain 10, "token launch" → Domain 5).
   - If no domain is mentioned, evaluate across all domains.

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
   - Reserve 95–100 only for markets explicitly about the exact entity/event or a direct causal dependency.
   - 90–94: Sustained, near-certain impact from the query topic (limit to top 1–2 items unless all are identical).
   - 80–89: Strong but not guaranteed relationship (shared catalyst, same actors, or clear downstream effect).
   - 70–79: Same category/domain with partial ties or secondary exposure.
   - Scores below 70 should be excluded entirely.
   - Penalize markets that only mention the topic tangentially.

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

            # Fallback: if too few semantic matches, augment with deterministic keyword search
            min_expected = max(5, user_limit or 5)
            if len(all_matches) < min_expected:
                fallback_limit = max(min_expected * 2, 15)
                fallback_events = self._keyword_sql_fallback(keywords, phrases, limit=fallback_limit)
                for event in fallback_events:
                    if str(event.id) not in seen_event_ids:
                        all_matches.append(event)
                        seen_event_ids.add(str(event.id))

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
            self._cached_perplexity_context = None
            self._cached_perplexity_queries = None
            self._last_thinking_trace = None

            # Pre-step: Add system context to query
            contextualized_query = f"""SYSTEM CONTEXT: You are a prediction markets chatbot with access to Polymarket (events table).

CRITICAL INSTRUCTION: Unless the user explicitly asks a generic question (e.g., "what is polymarket?", "how do prediction markets work?"), you MUST query the database and return actual markets/events from Polymarket.

Examples:
- "interest rates" → Find markets about interest rates in the database
- "trump" → Find markets about Trump in the database
- "AI markets" → Find markets about AI in the database
- "polymarket sports" → Find Polymarket sports markets
- "what is polymarket?" → Generic question, can answer without database

USER QUERY: {user_query}"""

            metric_field = self._detect_metric_field(user_query)

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
            self._platform_filter = analysis.get('platform_filter', 'BOTH')
            user_limit = analysis['user_limit']

            # Override strategy for simple ranking queries to avoid unnecessary reasoning
            strategy_normalized = strategy.lower() if isinstance(strategy, str) else ''
            if strategy_normalized != 'comparison' and self._is_simple_metric_query(user_query):
                strategy_normalized = 'sql'
                strategy = 'sql'
                self._log("info", "🎯 Simple metric query detected → forcing SQL strategy")

            needs_reasoning = strategy_normalized in {'batch', 'comparison'}

            if needs_reasoning:
                context = self._ensure_perplexity_context(user_query, intent)
                if context:
                    self._log("info", "🌐 Perplexity multi-query context attached")

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

            keywords, phrases = self._extract_query_keywords(user_query)

            # Prepare optional SQL prefilter only when domain filtering or specific nouns are involved
            sql_prefilter = None
            # Skip prefiltering for simple metric queries (they should use direct SQL)
            if not self._is_simple_metric_query(user_query) and (self._cached_domain_filter or keywords):
                sql_prefilter = self._sql_prefilter_events(
                    keywords=keywords,
                    phrases=phrases,
                    domain_filter=self._cached_domain_filter,
                    limit=600,
                    order_field=metric_field,
                )

            # Execute based on strategy
            if strategy == 'sql':
                # For simple metric queries, use direct SQL execution without prefiltering
                if self._is_simple_metric_query(user_query):
                    self._log("info", "🎯 Simple metric query → direct SQL execution")
                    result = self.execute_sql_query(sql_info, user_query, intent, output_format, user_limit)
                    self._log("info", "✅ Direct SQL execution complete")
                    return result
                else:
                    # For complex SQL queries, use prefiltering and batch processing
                    if needs_reasoning and not self._cached_perplexity_context:
                        self._ensure_perplexity_context(user_query, intent)
                    result = self.batch_process_events(
                        user_query,
                        intent,
                        output_format,
                        domain_filter=self._cached_domain_filter,
                        user_limit=user_limit,
                        external_context=self._cached_perplexity_context,
                        prefetched_events=sql_prefilter,
                    )
                    self._log("info", "✅ SQL-assisted Gemini scoring complete")
                    if not self.last_structured_results and sql_prefilter:
                        fallback_structured = []
                        for event in sql_prefilter[:DEFAULT_DISPLAY_LIMIT]:
                            structured = self._structured_from_event(event, strategy='sql')
                            if structured:
                                fallback_structured.append(structured)
                        if fallback_structured:
                            self._record_structured_results(fallback_structured)
                    return result
            elif strategy == 'comparison':
                self._log("info", "⚙️ Step 2: Executing comparison queries...")
                if needs_reasoning and not self._cached_perplexity_context:
                    self._ensure_perplexity_context(user_query, intent)
                result = self.execute_comparison_queries(
                    comparison_info,
                    user_query,
                    intent,
                    output_format,
                    user_limit,
                    external_context=self._cached_perplexity_context,
                )
                self._log("info", f"✅ Comparison complete")
                return result
            elif strategy == 'batch':
                self._log("info", "⚙️ Step 2: Starting batch semantic search...")
                if needs_reasoning and not self._cached_perplexity_context:
                    self._ensure_perplexity_context(user_query, intent)
                result = self.batch_process_events(
                    user_query,
                    intent,
                    output_format,
                    domain_filter=self._cached_domain_filter,
                    user_limit=user_limit,
                    external_context=self._cached_perplexity_context,
                    prefetched_events=sql_prefilter,
                )
                self._log("info", f"✅ Batch processing complete")
                if not self.last_structured_results and sql_prefilter:
                    fallback_structured = []
                    for event in sql_prefilter[:DEFAULT_DISPLAY_LIMIT]:
                        structured = self._structured_from_event(event, strategy='batch')
                        if structured:
                            fallback_structured.append(structured)
                    if fallback_structured:
                        self._record_structured_results(fallback_structured)
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
    api_key = os.getenv('GEMINI_API_KEY', 'AIzaSyAxDVBBTQGcR9Em_2vP_8960ayYWl8UFKk')
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
