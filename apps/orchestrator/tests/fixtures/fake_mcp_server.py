"""Minimal MCP stdio server for driver tests."""

from mcp.server.fastmcp import FastMCP

server = FastMCP("fake")


@server.tool()
def echo(text: str) -> str:
    """Reverse the input text."""
    return text[::-1]


if __name__ == "__main__":
    server.run()
