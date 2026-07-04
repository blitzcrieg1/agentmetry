"""search — read-only web search MCP driver (Serper preferred, Tavily fallback).

Mounted from vault/.system/drivers.json (disabled by default). API keys reach
this process only via the driver's env_allow list:

    { "name": "search", "command": "<venv python>", "args": ["<this file>"],
      "env_allow": ["SERPER_API_KEY", "TAVILY_API_KEY"], "enabled": true }
"""

from __future__ import annotations

import os

import httpx
from mcp.server.fastmcp import FastMCP

server = FastMCP("search")

_MAX_RESULTS = 10


def _serper(query: str, count: int, key: str) -> list[tuple[str, str, str]]:
    resp = httpx.post(
        "https://google.serper.dev/search",
        headers={"X-API-KEY": key, "Content-Type": "application/json"},
        json={"q": query, "num": count},
        timeout=15.0,
    )
    resp.raise_for_status()
    return [
        (r.get("title", ""), r.get("link", ""), r.get("snippet", ""))
        for r in resp.json().get("organic", [])[:count]
    ]


def _tavily(query: str, count: int, key: str) -> list[tuple[str, str, str]]:
    resp = httpx.post(
        "https://api.tavily.com/search",
        json={"api_key": key, "query": query, "max_results": count},
        timeout=15.0,
    )
    resp.raise_for_status()
    return [
        (r.get("title", ""), r.get("url", ""), (r.get("content", "") or "")[:300])
        for r in resp.json().get("results", [])[:count]
    ]


def search_web(query: str, count: int = 5) -> str:
    """Run the search against whichever provider has a key configured."""
    count = max(1, min(int(count), _MAX_RESULTS))
    serper_key = os.environ.get("SERPER_API_KEY", "")
    tavily_key = os.environ.get("TAVILY_API_KEY", "")

    if serper_key:
        results = _serper(query, count, serper_key)
    elif tavily_key:
        results = _tavily(query, count, tavily_key)
    else:
        raise RuntimeError(
            "No search API key configured — set SERPER_API_KEY or TAVILY_API_KEY "
            "and add it to the driver's env_allow in vault/.system/drivers.json"
        )

    if not results:
        return "(no results)"
    return "\n\n".join(
        f"### {title}\n{url}\n{snippet}" for title, url, snippet in results
    )


@server.tool()
def web(query: str, count: int = 5) -> str:
    """Search the web; returns the top results as markdown (title, URL, snippet)."""
    return search_web(query, count)


if __name__ == "__main__":
    server.run()
