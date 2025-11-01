# Query Logger - Standalone Usage Guide

## Overview

The **QueryLogger** is a standalone logging system that tracks query execution details. It's been extracted from the bot code and works independently.

## Location

**File:** `query_logger.py`
**Log Output:** `query_execution.log`

## Features

- ✅ Logs query text and timestamp
- ✅ Logs strategy chosen (SQL vs AI)
- ✅ Logs SQL queries with platform and parameters
- ✅ Logs AI prompts and responses step-by-step
- ✅ Logs results count and execution time
- ✅ Writes to both file and console simultaneously

## Basic Usage

```python
from query_logger import QueryLogger

# Create logger instance
logger = QueryLogger()  # Logs to query_execution.log by default
# Or specify custom log file:
# logger = QueryLogger(log_file='my_custom.log')

# Start a new query
logger.start_query("top 10 markets by volume")

# Log the strategy decision
logger.log_strategy("FAST SQL", "Simple ranking query detected")

# Log SQL query execution
logger.log_sql(
    query="SELECT * FROM markets WHERE active=1 ORDER BY volume DESC LIMIT 10",
    platform="Polymarket",
    params=None  # Optional
)

# Log results
logger.log_results(count=10, time_elapsed=0.34)

# End query logging
logger.end_query()
```

## SQL Query Example

```python
from query_logger import QueryLogger

logger = QueryLogger()

logger.start_query("highest liquidity kalshi markets")
logger.log_strategy("FAST SQL", "Ranking query with metric detected")

logger.log_sql(
    "SELECT * FROM kalshi_markets WHERE is_active=1 ORDER BY liquidity DESC LIMIT 20",
    "Kalshi"
)

logger.log_results(20, 0.45)
logger.end_query()
```

**Output in `query_execution.log`:**
```
================================================================================
QUERY: highest liquidity kalshi markets
TIMESTAMP: 2025-11-01 14:09:02
================================================================================

STRATEGY CHOSEN: FAST SQL
REASON: Ranking query with metric detected

--- SQL QUERY ---
Platform: Kalshi
Query: SELECT * FROM kalshi_markets WHERE is_active=1 ORDER BY liquidity DESC LIMIT 20

--- RESULTS ---
Markets Found: 20
Time Elapsed: 0.45s
================================================================================
```

## AI Query Example

```python
from query_logger import QueryLogger

logger = QueryLogger()

logger.start_query("markets affected by inflation")
logger.log_strategy("AI SEMANTIC SEARCH", "Complex semantic query requiring AI")

# Log first AI batch
prompt1 = """You are evaluating markets.
Query: markets affected by inflation
Evaluate these 200 markets..."""

response1 = "market:123:95:Directly about inflation|market:456:88:CPI related"

logger.log_ai_prompt("Batch 1 Matching", prompt1, response1)

# Log second AI batch
prompt2 = """You are evaluating markets.
Query: markets affected by inflation
Evaluate these 200 markets..."""

response2 = "market:789:92:Fed policy tied to inflation"

logger.log_ai_prompt("Batch 2 Matching", prompt2, response2)

logger.log_results(18, 21.34)
logger.end_query()
```

**Output in `query_execution.log`:**
```
================================================================================
QUERY: markets affected by inflation
TIMESTAMP: 2025-11-01 14:10:15
================================================================================

STRATEGY CHOSEN: AI SEMANTIC SEARCH
REASON: Complex semantic query requiring AI

--- AI PROMPT: Batch 1 Matching ---
Input (123 chars):
You are evaluating markets.
Query: markets affected by inflation
Evaluate these 200 markets...

Output (67 chars):
market:123:95:Directly about inflation|market:456:88:CPI related

--- AI PROMPT: Batch 2 Matching ---
Input (123 chars):
You are evaluating markets.
Query: markets affected by inflation
Evaluate these 200 markets...

Output (46 chars):
market:789:92:Fed policy tied to inflation

--- RESULTS ---
Markets Found: 18
Time Elapsed: 21.34s
================================================================================
```

## Advanced Features

### Custom Log File

```python
logger = QueryLogger(log_file='custom_queries.log')
```

### Log Errors

```python
try:
    # Your query processing
    pass
except Exception as e:
    logger.log_error(f"Query failed: {str(e)}")
    logger.log_results(0, time_elapsed)
    logger.end_query()
```

### Get Log Contents Programmatically

```python
logger.start_query("test query")
logger.log("Some message")

# Get all log messages for current query
log_contents = logger.get_log_contents()
print(log_contents)  # ['QUERY: test query', 'Some message', ...]
```

### Clear Log File

```python
logger.clear_log_file()  # Clears query_execution.log
```

## Integration Example

Here's how to integrate the logger into your own query processing:

```python
import time
from query_logger import QueryLogger

def process_query(user_query):
    logger = QueryLogger()
    start_time = time.time()

    try:
        # Start logging
        logger.start_query(user_query)

        # Determine strategy
        if is_simple_query(user_query):
            logger.log_strategy("FAST SQL", "Simple ranking detected")

            # Execute SQL
            sql = "SELECT * FROM markets ORDER BY volume DESC LIMIT 10"
            logger.log_sql(sql, "Polymarket")
            results = execute_sql(sql)

            # Log results
            elapsed = time.time() - start_time
            logger.log_results(len(results), elapsed)
            logger.end_query()

        else:
            logger.log_strategy("AI SEMANTIC SEARCH", "Complex query needs AI")

            # Process with AI
            for batch_num, batch in enumerate(batches, 1):
                prompt = create_prompt(batch)
                response = call_ai(prompt)
                logger.log_ai_prompt(f"Batch {batch_num}", prompt, response)

            # Log results
            elapsed = time.time() - start_time
            logger.log_results(len(results), elapsed)
            logger.end_query()

    except Exception as e:
        elapsed = time.time() - start_time
        logger.log_error(str(e))
        logger.log_results(0, elapsed)
        logger.end_query()
        raise
```

## Test the Logger

Run the included test:

```bash
python3 query_logger.py
```

This will create example log entries in `query_execution.log`.

## Log File Management

The log file **appends** by default (doesn't overwrite). To manage:

### Clear the log:
```bash
> query_execution.log
```

### Archive old logs:
```bash
mv query_execution.log query_execution_$(date +%Y%m%d).log
```

### View recent logs:
```bash
tail -50 query_execution.log
```

### Search logs:
```bash
grep "STRATEGY CHOSEN" query_execution.log
grep "AI SEMANTIC SEARCH" query_execution.log
grep "Time Elapsed" query_execution.log
```

## Performance Tips

- **Long prompts are truncated** to 500 chars in the log for readability
- Logs write to file **immediately** (no buffering)
- Console output happens **simultaneously** with file writing
- No performance overhead when logger is not used

## Summary

The standalone `QueryLogger` provides full transparency into query execution without requiring the full bot code. Use it to:

- Debug query strategies
- Understand SQL vs AI decisions
- Track AI prompt engineering
- Monitor query performance
- Audit query history

**File:** `query_logger.py`
**Output:** `query_execution.log`
**Test:** `python3 query_logger.py`
