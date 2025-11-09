# Query Logging System Documentation

## Overview

The intelligent Polymarket bot now includes a comprehensive query logging system that tracks **every detail** of query execution:

- ✅ Query text and timestamp
- ✅ Strategy chosen (SQL vs AI)
- ✅ SQL queries executed (for SQL strategy)
- ✅ All AI prompts and responses (for AI strategy)
- ✅ Results count and execution time

All logs are written to **`query_execution.log`** in the project root.

---

## Log Format

### SQL Strategy Example

```
================================================================================
QUERY: top 10 markets by volume in polymarket
TIMESTAMP: 2025-11-01 14:05:23
================================================================================

STRATEGY CHOSEN: FAST SQL
REASON: Simple ranking query detected (has ranking keyword + metric)

--- SQL QUERY ---
Platform: Polymarket
Query: SELECT * FROM events WHERE is_active=1 ORDER BY volume DESC LIMIT 10

--- RESULTS ---
Markets Found: 10
Time Elapsed: 0.34s
================================================================================
```

### AI Strategy Example

```
================================================================================
QUERY: markets affected by Federal Reserve rate changes
TIMESTAMP: 2025-11-01 14:06:15
================================================================================

STRATEGY CHOSEN: AI SEMANTIC SEARCH
REASON: Complex query requiring semantic understanding

--- AI PROMPT: Batch 1 Multi-Platform Matching ---
Input (1543 chars):

You are a prediction market evaluator.

USER QUERY: markets affected by Federal Reserve rate changes
USER INTENT: Find markets related to: markets affected by Federal Reserve rate changes

BATCH 1 of markets to evaluate (from Polymarket):
[
 {
  "id": "12345",
  "title": "Will the Fed raise rates in March 2025?",
  "category": "Politics"
 },
 ...
]

YOUR TASK:
1. Evaluate each market's relevance to the user query
2. Assign a relevance score (0-100):
   - 95-100: Directly about the exact topic
   - 90-94: Strong sustained impact
   ...

Output (287 chars):
12345:95:Directly about Fed rate decision|67890:88:Treasury yields tied to Fed policy|23456:92:Federal Reserve rate market...

--- AI PROMPT: Batch 2 Multi-Platform Matching ---
Input (1621 chars):
...

--- RESULTS ---
Markets Found: 15
Time Elapsed: 18.45s
================================================================================
```

---

## What Gets Logged

### For Every Query:

1. **Header**
   - Query text
   - Timestamp (YYYY-MM-DD HH:MM:SS)

2. **Strategy Decision**
   - Chosen strategy (FAST SQL or AI SEMANTIC SEARCH)
   - Reason for choosing that strategy

### For SQL Queries:

3. **SQL Execution**
   - Platform (Polymarket)
   - Exact SQL query executed
   - Parameters (if any)

### For AI Queries:

3. **AI Prompts** (Step-by-Step)
   - Each Gemini API call logged separately
   - Step name (e.g., "Batch 1 Multi-Platform Matching")
   - Full input prompt (truncated to 500 chars in log)
   - Full output response (truncated to 500 chars in log)

4. **Multiple Batch Processing**
   - If query uses batch processing, ALL batches are logged
   - Parallel execution is captured in chronological order

### For All Queries:

5. **Results**
   - Number of markets found
   - Total execution time (seconds)

---

## How to Use

### Method 1: Automatic Logging (Default)

The bot automatically logs all queries when enabled:

```python
from intelligent_multi_platform_bot import IntelligentMultiPlatformBot

bot = IntelligentMultiPlatformBot(
    api_key=GEMINI_API_KEY,
    enable_query_logging=True  # Default: enabled
)

# All queries automatically logged to query_execution.log
bot.process_query("top 10 markets by volume")
```

### Method 2: Disable Logging

```python
bot = IntelligentMultiPlatformBot(
    api_key=GEMINI_API_KEY,
    enable_query_logging=False  # Disable logging
)
```

### Method 3: Run Test Script

```bash
cd /Users/alayshah/Desktop/NthOrderMarket
python3 test_query_logging.py
```

This runs example queries and shows the logging in action.

---

## Log File Location

**File:** `query_execution.log`
**Path:** `/Users/alayshah/Desktop/NthOrderMarket/query_execution.log`

The log file:
- ✅ Appends to existing logs (doesn't overwrite)
- ✅ Prints to console AND file simultaneously
- ✅ One entry per query with clear separators

---

## Example Queries and Expected Logs

### Query 1: "top 5 markets by volume"

**Expected Strategy:** FAST SQL

**Log Contents:**
```
STRATEGY CHOSEN: FAST SQL
REASON: Simple ranking query detected (has ranking keyword + metric)

--- SQL QUERY ---
Platform: Polymarket
Query: SELECT * FROM events WHERE is_active=1 ORDER BY volume DESC LIMIT 5

--- RESULTS ---
Markets Found: 5
Time Elapsed: 0.12s
```

### Query 2: "highest liquidity markets"

**Expected Strategy:** FAST SQL

**Log Contents:**
```
STRATEGY CHOSEN: FAST SQL
REASON: Simple ranking query detected (has ranking keyword + metric)

--- SQL QUERY ---
Platform: Polymarket
Query: SELECT * FROM events WHERE is_active=1 ORDER BY liquidity DESC LIMIT 20

--- SQL QUERY ---
Platform: Polymarket  
Query: SELECT * FROM events WHERE is_active=1 ORDER BY liquidity DESC LIMIT 20

--- RESULTS ---
Markets Found: 20
Time Elapsed: 0.45s
```

### Query 3: "markets that benefit from oil price increases"

**Expected Strategy:** AI SEMANTIC SEARCH

**Log Contents:**
```
STRATEGY CHOSEN: AI SEMANTIC SEARCH
REASON: Complex query requiring semantic understanding

--- AI PROMPT: Batch 1 Multi-Platform Matching ---
Input (2145 chars):
You are a prediction market evaluator.

USER QUERY: markets that benefit from oil price increases
...

Output (421 chars):
polymarket:123:92:Energy sector stocks directly tied to oil|polymarket:456:85:Transportation costs affected...

--- AI PROMPT: Batch 2 Multi-Platform Matching ---
...

--- RESULTS ---
Markets Found: 18
Time Elapsed: 21.34s
```

---

## Understanding the Logs

### Strategy Selection Logic

**FAST SQL** is chosen when:
- Query has ranking keyword: "top", "highest", "biggest", "largest", "most", "best"
- **AND** has metric keyword: "volume", "liquidity", "open interest"
- **OR** has "by [metric]" construction

**AI SEMANTIC SEARCH** is chosen for everything else:
- Semantic queries: "affected by", "related to", "impacted by"
- Complex relationships: "benefit from", "inversely related to"
- No clear ranking metric

### SQL Query Format

```
SELECT * FROM [table]
WHERE is_active=1
ORDER BY [metric] DESC
LIMIT [N]
```

**Metric** is one of:
- `volume` (default)
- `liquidity`
- `open_interest`

### AI Prompt Structure

Each batch prompt includes:
1. User's original query
2. Intent description
3. Batch number and market data
4. Scoring instructions (0-100 scale)
5. Output format specification

---

## Performance Tracking

The logs show execution time for each query:

| Strategy | Typical Time | Example |
|----------|--------------|---------|
| FAST SQL | <1 second | 0.34s |
| AI SEMANTIC | 15-30 seconds | 18.45s |

Use this to:
- ✅ Verify queries are using the right strategy
- ✅ Identify slow queries
- ✅ Understand batch processing overhead

---

## Troubleshooting with Logs

### Problem: Query is too slow

**Check:** `STRATEGY CHOSEN` in log
- If "FAST SQL" → Should be <1 second (database issue)
- If "AI SEMANTIC SEARCH" → 15-30s is normal (check if SQL would work instead)

### Problem: Wrong results

**Check:** SQL queries or AI prompts in log
- SQL: Verify the ORDER BY clause matches your intent
- AI: Check if the prompt accurately represents your query

### Problem: No results found

**Check:** SQL WHERE clause or AI batch responses
- SQL: Verify `is_active=1` filter
- AI: Check if any batches returned "NONE"

---

## Integration with MCP Server

The MCP server's `intelligent_search_multi_platform` tool uses this same logging system.

When querying through Claude Desktop:
1. Logs are written to `query_execution.log`
2. Check the log to see exactly what Claude executed
3. Understand why a query was slow or returned unexpected results

---

## Log Rotation

The log file grows over time. To reset:

```bash
# Clear the log file
> query_execution.log

# Or rename to archive
mv query_execution.log query_execution_$(date +%Y%m%d).log
```

---

## Summary

**Query Logging Shows:**
- ✅ Every query with timestamp
- ✅ Strategy decision (SQL vs AI)
- ✅ Exact SQL queries (if SQL)
- ✅ All AI prompts step-by-step (if AI)
- ✅ Results count and timing

**Log File:** `query_execution.log`
**Test Script:** `python3 test_query_logging.py`
**Default:** Enabled (set `enable_query_logging=False` to disable)

This transparency lets you understand exactly how your queries are processed and why they return the results they do!
