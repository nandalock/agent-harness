"""Run the built-in MCP server over stdio (for `mcp-client` stdio config)."""
from .server import mcp

if __name__ == "__main__":
    mcp.run()
