"""Command line interface for the Prediction MCP server."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import click

from . import __version__
from .config import ConfigManager
from .db_sync_service import run_sync_service, sync_databases
from .market_updater import run_scheduler as run_market_scheduler, update_all_market_data


@click.group()
@click.version_option(version=__version__, prog_name="prediction-mcp-server")
def main() -> None:
    """Prediction market MCP server utilities."""


@main.command()
@click.option(
    "--db-path",
    type=click.Path(path_type=Path),
    help="Path to read-only prediction market SQLite database.",
)
@click.option(
    "--gemini-api-key",
    help="Gemini API key for intelligent chat tool.",
)
@click.option(
    "--default-limit",
    type=int,
    help="Default result limit for SQL tools (falls back to 25).",
)
@click.option(
    "--config-file",
    type=click.Path(path_type=Path),
    help="Location of the configuration .env file (default: ./.env).",
)
def init(
    db_path: Optional[Path],
    gemini_api_key: Optional[str],
    default_limit: Optional[int],
    config_file: Optional[Path],
) -> None:
    """Create or update the .env configuration file."""
    manager = ConfigManager(config_file)

    success = manager.setup_env_file(
        db_path=str(db_path) if db_path else None,
        gemini_api_key=gemini_api_key,
        default_limit=default_limit,
    )

    if not success:
        click.echo("Failed to create configuration.", err=True)
        sys.exit(1)


@main.command()
@click.option(
    "--transport",
    type=click.Choice(["stdio", "http"]),
    default="stdio",
    show_default=True,
    help="Transport to use for MCP communication.",
)
@click.option(
    "--host",
    default="127.0.0.1",
    show_default=True,
    help="Host binding for HTTP transport.",
)
@click.option(
    "--port",
    type=int,
    default=8001,
    show_default=True,
    help="Port binding for HTTP transport.",
)
@click.option(
    "--config-file",
    type=click.Path(path_type=Path),
    help="Optional path to configuration .env file.",
)
def serve(
    transport: str,
    host: str,
    port: int,
    config_file: Optional[Path],
) -> None:
    """Start the Prediction MCP server."""
    # Import lazily so that environment variables loaded by ConfigManager are respected.
    from .server import PredictionMCPServer

    manager = ConfigManager(config_file)

    if not manager.validate_config():
        click.echo("Configuration invalid or database missing.", err=True)
        click.echo(manager.get_config_summary(), err=True)
        click.echo("Run 'prediction-mcp-server init' to configure.", err=True)
        sys.exit(1)

    server = PredictionMCPServer(config_file)

    if transport == "stdio":
        server.run(transport="stdio")
    else:
        click.echo(
            f"Starting Prediction MCP server on http://{host}:{port} (transport={transport})"
        )
        server.run(transport=transport, host=host, port=port)


@main.command()
@click.option(
    "--config-file",
    type=click.Path(path_type=Path),
    help="Optional path to configuration .env file.",
)
def status(config_file: Optional[Path]) -> None:
    """Show current configuration status."""
    manager = ConfigManager(config_file)
    click.echo(manager.get_config_summary())

    if manager.validate_config():
        click.echo("\nConfiguration looks good. Start the server with: prediction-mcp-server serve")
    else:
        click.echo(
            "\nConfiguration incomplete. Run 'prediction-mcp-server init' or fix the above issues."
        )


@main.command("update-data")
@click.option(
    "--interval",
    type=int,
    default=20,
    show_default=True,
    help="Seconds between update loops. Use 0 to run a single refresh.",
)
@click.option(
    "--max-workers",
    type=int,
    help="Thread pool size for data refresh (default 8).",
)
def update_data(interval: int, max_workers: Optional[int]) -> None:
    """Refresh prediction market data (single run or continuous scheduler)."""
    if interval <= 0:
        update_all_market_data(max_workers=max_workers)
    else:
        run_market_scheduler(interval_seconds=interval, max_workers=max_workers)


@main.command("sync-service")
@click.option(
    "--interval",
    type=float,
    default=5.0,
    show_default=True,
    help="Seconds between sync operations.",
)
def sync_service(interval: float) -> None:
    """Continuously copy write DB into read replica."""
    run_sync_service(interval=interval)


@main.command("sync-once")
def sync_once() -> None:
    """Perform a single sync from write DB to read DB."""
    success = sync_databases()
    if not success:
        sys.exit(1)


if __name__ == "__main__":  # pragma: no cover
    main()
