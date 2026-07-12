![WebSearch MCP](../images/title.png)

<div align="center">

English | [简体中文](../README.md)

A standard MCP web-search server for Cherry Studio, Claude Code, and Codex

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](../LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![MCP stdio](https://img.shields.io/badge/MCP-stdio-green.svg)](https://modelcontextprotocol.io/)

</div>

## Overview

WebSearch MCP uses Grok for AI-driven web search and Tavily for structured search results, page extraction, and site mapping. It runs over the standard MCP stdio transport and does not depend on private configuration from any single client.

```text
MCP Client --stdio--> WebSearch MCP
                       |-- web_search --> Grok + optional Tavily sources
                       |-- web_fetch  --> Tavily Extract
                       `-- web_map    --> Tavily Map
```

Highlights:

- Grok search through an OpenAI-compatible API, including per-request model selection.
- Tavily Search, Extract, and Map.
- Multiple Tavily keys separated by commas, semicolons, or newlines, with round-robin selection.
- Cached search sources retrievable through `get_sources`.
- Simple JSON Schemas and structured tool results.
- Windows parent-process monitoring for long-running stdio clients.

## Installation

Python 3.10+ and [uv](https://docs.astral.sh/uv/getting-started/installation/) are required. Every example installs from:

```text
https://github.com/Timmyzzo/WebSearch-MCP
```

### Cherry Studio

Add this server in Cherry Studio's MCP settings:

```json
{
  "mcpServers": {
    "grok-search": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/Timmyzzo/WebSearch-MCP",
        "grok-search"
      ],
      "env": {
        "GROK_API_URL": "https://your-api-endpoint.example/v1",
        "GROK_API_KEY": "your-grok-api-key",
        "TAVILY_API_KEY": "tvly-your-tavily-key"
      }
    }
  }
}
```

### Claude Code

```bash
claude mcp remove grok-search
claude mcp add-json grok-search --scope user '{
  "type": "stdio",
  "command": "uvx",
  "args": [
    "--from",
    "git+https://github.com/Timmyzzo/WebSearch-MCP",
    "grok-search"
  ],
  "env": {
    "GROK_API_URL": "https://your-api-endpoint.example/v1",
    "GROK_API_KEY": "your-grok-api-key",
    "TAVILY_API_KEY": "tvly-your-tavily-key"
  }
}'
```

Add `"--native-tls"` at the beginning of `args` when the host must use its system certificate store.

### Codex

Add the following to `~/.codex/config.toml`:

```toml
[mcp_servers.grok-search]
command = "uvx"
args = [
  "--from",
  "git+https://github.com/Timmyzzo/WebSearch-MCP",
  "grok-search",
]
startup_timeout_sec = 30
tool_timeout_sec = 180

[mcp_servers.grok-search.env]
GROK_API_URL = "https://your-api-endpoint.example/v1"
GROK_API_KEY = "your-grok-api-key"
TAVILY_API_KEY = "tvly-your-tavily-key"
```

## Environment variables

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `GROK_API_URL` | Yes | - | OpenAI-compatible API root with `/chat/completions` and `/models`. |
| `GROK_API_KEY` | Yes | - | Grok API key. |
| `GROK_MODEL` | No | `grok-4-fast` | Default Grok model. |
| `TAVILY_API_KEY` | No | - | One Tavily key. |
| `TAVILY_API_KEYS` | No | - | Multiple keys separated by commas, semicolons, or newlines; takes precedence over the single key. |
| `TAVILY_API_URL` | No | `https://api.tavily.com` | Tavily API root. |
| `TAVILY_ENABLED` | No | `true` | Enables or disables Tavily. |
| `GROK_DEBUG` | No | `false` | Enables debug logging. |
| `GROK_LOG_LEVEL` | No | `INFO` | Log level. |
| `GROK_LOG_DIR` | No | `logs` | Log directory. |
| `GROK_RETRY_MAX_ATTEMPTS` | No | `3` | Grok retry configuration. |
| `GROK_RETRY_MULTIPLIER` | No | `1` | Exponential backoff multiplier. |
| `GROK_RETRY_MAX_WAIT` | No | `10` | Maximum backoff in seconds. |

With Grok alone, `web_search` remains available. `web_fetch`, `web_map`, and extra Tavily sources require a Tavily key.

## MCP tools

Core tools:

- `web_search(query, platform="", model="", extra_sources=0)` returns a session ID, answer content, and source count.
- `get_sources(session_id)` retrieves all cached sources for a search.
- `web_fetch(url)` extracts Markdown through Tavily Extract.
- `web_map(url, instructions="", max_depth=1, max_breadth=20, limit=50, timeout=150)` discovers site URLs.
- `get_config_info()` returns masked configuration and tests Grok connectivity.
- `switch_model(model)` persists the default Grok model.

Optional phased planning tools are also available. Planning is not required before `web_search`, and every `thought` parameter is optional.

The server never edits local Claude Code, Codex, or Cherry Studio configuration. Configure built-in client web tools in the client itself when needed.

## Development

```bash
git clone https://github.com/Timmyzzo/WebSearch-MCP
cd WebSearch-MCP
uv sync --extra dev
uv run ruff check .
uv run pytest
```

Start the stdio server directly with:

```bash
uv run grok-search
```

## License

[MIT License](../LICENSE)
