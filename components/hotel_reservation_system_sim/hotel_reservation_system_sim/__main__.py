"""Serves the inventory over MCP's streamable HTTP transport, at `/mcp`."""

from .server import mcp

mcp.run(transport="streamable-http", host="0.0.0.0", port=8000)
