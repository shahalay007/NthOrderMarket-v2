#!/usr/bin/env python3
"""Bootstrap script for the Prediction MCP Server."""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

PROJECT_DIR = Path(__file__).resolve().parent
VENV_DIR = PROJECT_DIR / ".venv"


def print_header() -> None:
    print("=" * 60)
    print("🚀 Prediction MCP Server Installer")
    print("=" * 60)
    print(f"Project directory: {PROJECT_DIR}")
    print()


def ensure_python_version() -> None:
    if sys.version_info < (3, 10):
        print("❌ Python 3.10 or newer is required.")
        sys.exit(1)


def run(cmd: List[str], description: str, *, cwd: Optional[Path] = None, env: Optional[dict] = None) -> None:
    print(f"→ {description}")
    try:
        subprocess.run(cmd, check=True, cwd=str(cwd) if cwd else None, env=env)
    except subprocess.CalledProcessError as exc:
        print(f"   Command failed: {' '.join(cmd)}")
        print(f"   Exit code: {exc.returncode}")
        sys.exit(1)


def create_venv() -> Path:
    if VENV_DIR.exists():
        print("ℹ️  Reusing existing virtual environment (.venv)")
    else:
        print("→ Creating virtual environment (.venv)")
        run([sys.executable, "-m", "venv", str(VENV_DIR)], "Create virtual environment")
    return VENV_DIR


def venv_python() -> Path:
    if platform.system() == "Windows":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def install_package(py: Path) -> None:
    run([str(py), "-m", "pip", "install", "--upgrade", "pip"], "Upgrade pip", cwd=PROJECT_DIR)
    run([str(py), "-m", "pip", "install", "-e", "."], "Install prediction-mcp-server", cwd=PROJECT_DIR)


def run_cli(py: Path, args: List[str], description: str) -> None:
    cmd = [str(py), "-m", "prediction_mcp_server.cli"] + args
    run(cmd, description, cwd=PROJECT_DIR, env={**os.environ, "PREDICTION_CONFIG_FILE": str(PROJECT_DIR / ".env")})


def write_server_yaml(py: Path) -> None:
    server_config = {
        "mcpServers": {
            "prediction": {
                "command": str(py),
                "args": ["-m", "prediction_mcp_server.cli", "serve"],
                "env": {
                    "PREDICTION_CONFIG_FILE": str(PROJECT_DIR / ".env")
                },
                "cwd": str(PROJECT_DIR)
            }
        }
    }
    target = PROJECT_DIR / "server.yaml"
    target.write_text(json.dumps(server_config, indent=2))
    print(f"✅ MCP config snippet written to {target}")


def print_next_steps(py: Path) -> None:
    claude_path = None
    cursor_path = None
    system = platform.system()
    home = Path.home()
    if system == "Darwin":
        claude_path = home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    elif system == "Windows":
        claude_path = home / "AppData" / "Roaming" / "Claude" / "claude_desktop_config.json"
    else:
        claude_path = home / ".config" / "claude" / "claude_desktop_config.json"
    cursor_path = home / ".cursor" / "mcp.json"

    print()
    print("📋 Add this server to your MCP client config (example for Claude Desktop):")
    print(json.dumps({
        "mcpServers": {
            "prediction": {
                "command": str(py),
                "args": ["-m", "prediction_mcp_server.cli", "serve"],
                "env": {"PREDICTION_CONFIG_FILE": str(PROJECT_DIR / ".env")},
                "cwd": str(PROJECT_DIR)
            }
        }
    }, indent=2))
    print()
    print(f"• Suggested Claude config path: {claude_path}")
    print(f"• Cursor config path: {cursor_path}")
    print()
    print("🔥 To keep data fresh, run these in separate terminals:")
    if platform.system() == "Windows":
        activate_cmd = f"{VENV_DIR}\\Scripts\\activate"
    else:
        activate_cmd = f"source {VENV_DIR}/bin/activate"
    print(f"1. {activate_cmd}  # activate virtualenv")
    print("2. prediction-mcp-server update-data      # long-running market updater")
    print("3. prediction-mcp-server sync-service     # keeps read replica in sync")
    print("4. prediction-mcp-server serve            # start MCP server (if not launched by client)")
    print()
    print("✅ Setup complete! Update your MCP client config and restart it to connect.")


def main() -> None:
    print_header()
    ensure_python_version()
    create_venv()
    py = venv_python()
    install_package(py)
    print()
    print("🛠  Configure server environment (.env)")
    run_cli(py, ["init"], "Launch CLI init (follow prompts)")
    print()
    print("⏳ Running initial bootstrap (this may take a while)...")
    run_cli(py, ["update-data", "--interval", "0"], "Bootstrap market data (one-time)")
    run_cli(py, ["sync-once"], "Sync read replica")
    write_server_yaml(py)
    print_next_steps(py)


if __name__ == "__main__":
    main()
