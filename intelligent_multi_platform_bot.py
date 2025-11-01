"""
DEPRECATED: This file has been replaced by standalone components.

For query logging, use: query_logger.py
For MCP server tools, use: prediction-mcp-server/src/prediction_mcp_server/server.py

This file is kept for backward compatibility with existing imports.
"""
from query_logger import QueryLogger

# Re-export for backward compatibility
__all__ = ['QueryLogger']
