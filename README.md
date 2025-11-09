# NthOrder Market Intelligence

An end-to-end toolkit for exploring prediction markets on **Polymarket**. The project keeps a local SQLite replica in sync with the exchange, exposes an intelligent natural-language interface powered by Gemini, and offers an MCP bridge for IDE integrations.

The core goals are:
- maintain fresh, local copies of active markets (volumes, liquidity, metadata)
- let users ask questions in plain English and get the best matching markets
- pick the fastest strategy automatically (direct SQL for rankings, Gemini batch scoring for fuzzy searches)
- always filter to active markets

---

## System Overview

```
┌──────────────┐   API pull    ┌──────────────┐
│ update_market│ ─────────────▶│ polymarket.db│  (write replica)
│ _data.py     │               └──────┬───────┘
└──────────────┘                      │ sync via db_sync.py
                                      ▼
                             ┌──────────────────┐
                             │polymarket_read.db│  (read replica)
                             └──────────────────┘
                                      ▲
                                      │ ORM session in Gemini bot
                                      │
                              ┌───────┴─────────┐
                              │Flask app + UI   │
                              │(intelligent_app)│
                              └─────────────────┘
                                REST `/api/chat`
```

### Components

| Path | Description |
| ---- | ----------- |
| `intelligent_app.py` | Flask server + UI endpoints. Calls the Gemini bot and returns structured markets and reasoning. |
| `intelligent_gemini_bot.py` | Decision engine. Analyses a query once, decides SQL/BATCH/COMPARISON, enforces active-only filters, and surfaces strategy info + structured events. |
| `update_market_data.py` | High-throughput Polymarket fetcher (parallel threads, ~20s cadence). Writes to `polymarket.db` and enriches market metadata. |
| `db_sync.py` | Background service that copies the write DB into `polymarket_read.db` whenever no reads are active. |
| `prediction-mcp-server/` | Optional MCP server packaging the same workflow for Claude Desktop, Cursor, etc. Includes ChatGPT + Gemini tooling. |

---

## Data Refresh Workflow

1. **Polymarket ingestion** – `python update_market_data.py`
   - Bootstraps all active events, then runs in a 20s loop.
   - Fetches enrichment (outcome prices, liquidity, best bid/ask, open interest).
   - Uses 50-thread pool for fast per-event updates and flags inactive markets.

2. **Replica sync** – `python db_sync.py`
   - Tracks read locks via `ReadTracker` context manager.
   - Copies `polymarket.db` ➟ `polymarket_read.db` when idle and verifies counts.

> Both scripts can run continuously in their own terminal sessions. The Flask app will keep using the latest replica on disk.

---

## Query Processing Flow

1. **System prompt** – The bot is reminded to answer with real Polymarket markets unless the question is generic.
2. **Single analysis call** – `analyze_query_all_in_one()` asks Gemini to return:
   - intent + filters + requested limit
   - preferred strategy (`SQL`, `BATCH`, `COMPARISON`)
   - required columns / domain hints
3. **Strategy selection**
   - Simple ranking language ("top 10 … by volume") forces SQL regardless.
   - Batch/comparison paths may pull Perplexity context for deeper reasoning.
4. **Execution**
   - **SQL**: sanitize query, enforce `is_active = 1`, append ordering, stream results.
   - **Batch**: slice active events, send to Gemini for relevance scoring, keep ≥70.
   - **Comparison**: execute multiple SQL aggregates, combine into markdown.
5. **Structured output** – Each event record includes title, volume, liquidity, domain/category, URL, and any reasoning from batch mode. This powers table sorting/filtering on the front end.

---

## Requirements & Environment

- Python 3.9+
- SQLite 3.35+
- API keys
  - `GEMINI_API_KEY` (required)
  - `OPENAI_API_KEY` (optional, for MCP ChatGPT tool)
  - `PERPLEXITY_API_KEY` (optional, richer reasoning)

Create an `.env` file at the repo root or export variables manually:

```
GEMINI_API_KEY=your_gemini_key
PORT=5001          # optional, defaults to 5001
DEBUG=False        # optional
PREDICTION_DB_PATH=polymarket_read.db
```

Install dependencies once:

```bash
pip install -r requirements.txt
```

---

## Running the Stack

In separate terminals (recommended):

1. **Polymarket updater**
   ```bash
   python update_market_data.py
   ```
2. **Replica sync**
   ```bash
   python db_sync.py
   ```
3. **Flask app**
   ```bash
   python intelligent_app.py
   ```
   - UI: `http://localhost:5001`
   - Logs: `/tmp/intelligent_app.log`

You can stop any service with `Ctrl+C` or `kill <pid>`; restarting picks up from the current DB snapshot.

### Verifying Data Fill

- Polymarket counts:
  ```bash
  python - <<'PY'
  import sqlite3
  conn = sqlite3.connect('polymarket.db')
  cur = conn.cursor()
  cur.execute('SELECT COUNT(*) FROM events WHERE is_active = 1')
  print(cur.fetchone()[0])
  conn.close()
  PY
  ```

---

## API Highlights

`intelligent_app.py` exposes a simple REST surface:

| Endpoint | Method | Description |
| -------- | ------ | ----------- |
| `/` | GET | Main HTML interface. |
| `/api/chat` | POST JSON `{"message": "…"}` | Runs Gemini pipeline. Payload includes `response`, `events`, `thinking`, etc. |
| `/api/filter-events` | POST | Client-side filtering helper. |
| `/api/top-events` | GET | Top Polymarket events by volume. |
| `/api/stats` | GET | Basic Polymarket DB stats. |
| `/logs` | GET | Lightweight log viewer. |

Responses from `/api/chat` always reflect the chosen strategy (visible in server logs) and include structured records that the UI renders in a sortable list.

---

## MCP Server (Optional)

`prediction-mcp-server` packages the same data/logic for Model Context Protocol clients.

Key commands:

```bash
cd prediction-mcp-server
python install.py              # guided setup
uvx prediction-mcp-server init # configure DB paths + keys
uvx prediction-mcp-server serve
```

Notable tools:
- `intelligent_market_analysis` – mirrors the Gemini pipeline.
- `chatgpt_market_analysis` – OpenAI-backed reasoning with Polymarket context.
- `list_*` / `search_*` – SQL utilities for the Polymarket dataset.

See `prediction-mcp-server/README.md` for the full command set.

---

## Development Notes

- **Active-only enforcement**: all Polymarket queries inject `is_active = 1`.
- **Logging**: key decisions (strategy, keywords, Perplexity queries) are written through the Flask in-memory logger and stdout.
- **Extensibility ideas**: add semantic batching enhancements, expose strategy info in the UI, or stream progress updates via SSE/WebSockets.

---

## Troubleshooting

| Symptom | Fix |
| ------- | --- |
| Blank results | Ensure updaters are running and DBs exist (`ls -lh *.db`). |
| Gemini errors | Verify `GEMINI_API_KEY` and network access. |
| MCP tools missing | Re-run `uvx prediction-mcp-server init` and ensure env vars propagate. |

---

## License

No explicit license file is provided. Treat the codebase as proprietary unless a license is added.
