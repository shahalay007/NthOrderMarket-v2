# Prediction MCP Server

Model Context Protocol (MCP) server exposing Polymarket-style prediction market data and Gemini-powered analysis workflows. Inspired by the Alpaca MCP server, this package makes the local `polymarket_read.db` dataset and the `IntelligentGeminiBot` flow available inside MCP-compatible clients such as Claude Desktop, Cursor, and VS Code.

## Features
- 🔍 Search, filter, and inspect active prediction markets from the local SQLite replica.
- 📊 Retrieve high-volume markets, category breakdowns, and market-level statistics.
- 🤖 Ask natural language questions that are routed through the existing `IntelligentGeminiBot` decision engine.
- ⚙️ Simple CLI (`prediction-mcp-server`) for configuration, status checks, and running the server over stdio or HTTP.

## MCP Tools
- `list_top_markets` — ranked slice of active markets with optional domain filter and sort mode.
- `search_markets` — full-text search across titles, descriptions, and slugs.
- `market_details` — deep dive on an individual market by slug or id.
- `market_stats` — aggregate stats plus top domains by volume.
- `intelligent_market_analysis` — mirrors the `IntelligentGeminiBot` end-to-end workflow.

## One-Line Installer
Run the bundled installer to set up a virtualenv, install dependencies, create `.env`, bootstrap the database, and write a ready-to-copy MCP configuration snippet.

```bash
python install.py
```

The script will:
1. Create `.venv/` and install `prediction-mcp-server` in editable mode.
2. Launch `prediction-mcp-server init` so you can set the read replica path and `GEMINI_API_KEY`.
3. Run an initial data fetch (`update-data --interval 0`) and `sync-once`.
4. Generate `server.yaml` with the correct command/args/env for Claude or Cursor.

## Manual Quick Start
```bash
# Configure (optional prompts for DB path and Gemini key, use .venv if created)
prediction-mcp-server init

# Run the server (stdio transport for MCP clients)
prediction-mcp-server serve
```

Set these environment variables (or populate them via `init`):
- `PREDICTION_DB_PATH`: path to your read-only SQLite database (defaults to `polymarket_read.db`).
- `PREDICTION_WRITE_DB_PATH`: writable primary database (defaults to `polymarket.db`).
- `PREDICTION_READ_DB_PATH`: override for read replica path.
- `GEMINI_API_KEY`: Google Gemini API key, required for the intelligent chat tool.
- `PREDICTION_DEFAULT_LIMIT`: optional default result limit for SQL tools.
- `PREDICTION_CONFIG_FILE`: explicit path to the `.env` file (useful for MCP client configs).

Add the server to your MCP client configuration using the `prediction-mcp-server` command (or the `python -m prediction_mcp_server.cli serve` form saved in `server.yaml`).

## Keeping Data Fresh

After running the installer (or setting things up manually), start these long-running processes—each in its own terminal tab:

```bash
# 1. Continuously fetch market data from Polymarket
prediction-mcp-server update-data

# 2. Mirror the write DB into the read replica used by the MCP tools
prediction-mcp-server sync-service

# (Optional) 3. Serve the MCP endpoint manually (most MCP clients launch it automatically)
prediction-mcp-server serve
```

To perform single-shot operations:
- `prediction-mcp-server update-data --interval 0` — run one full refresh.
- `prediction-mcp-server sync-once` — copy the write DB to the read replica once.
- `prediction-mcp-server status` — show the resolved config and database status.
