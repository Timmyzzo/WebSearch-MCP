![WebSearch MCP](../images/title.png)

<div align="center">

English | [简体中文](../README.md)

A standard MCP web-search server for Cherry Studio, Claude Code, and Codex

[![CI](https://github.com/Timmyzzo/WebSearch-MCP/actions/workflows/ci.yml/badge.svg)](https://github.com/Timmyzzo/WebSearch-MCP/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](../LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![MCP stdio](https://img.shields.io/badge/MCP-stdio-green.svg)](https://modelcontextprotocol.io/)

</div>

## What is WebSearch MCP?

WebSearch MCP combines Grok's AI-powered web search with Tavily search, page extraction, and site mapping behind a standard MCP stdio server. It does not depend on private client capabilities and never edits local Cherry Studio, Claude Code, or Codex configuration.

```text
MCP Client --stdio--> WebSearch MCP
                       |-- web_search --> Grok + optional Tavily sources
                       |-- get_sources --> cached search sources
                       |-- web_fetch  --> Tavily Extract
                       `-- web_map    --> Tavily Map
```

Typical uses include retrieving current official documentation, producing answers with traceable sources, extracting pages as Markdown, and reusing the same web tools across MCP clients.

## Project status

- P0 repository and test baseline: complete.
- P1 legacy crawler removal and modularization: complete.
- P2 Tavily multi-key reliability: complete.
- Next: P3 Grok primary/fallback models and retries.

See the [development roadmap](./DEVELOPMENT_ROADMAP.md) for requirements and acceptance criteria.

## Quick start

### 1. Requirements

- Python 3.10+
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- An OpenAI-compatible Grok API URL and key
- An optional Tavily key for `web_fetch`, `web_map`, and supplemental sources

### 2. Add the MCP server

Claude Code example for Linux/macOS:

```bash
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

For Cherry Studio, Claude Code on PowerShell, Codex, validation steps, and troubleshooting, see the [client setup guide](./CLIENT_SETUP_EN.md).

### 3. Verify

The client should discover these core tools:

```text
web_search
get_sources
web_fetch
web_map
get_config_info
switch_model
```

Call `get_config_info` first to inspect masked configuration and test the Grok `/models` endpoint.

## Configuration

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `GROK_API_URL` | Yes | - | OpenAI-compatible API root with `/chat/completions` and `/models`. |
| `GROK_API_KEY` | Yes | - | Grok API key. |
| `GROK_MODEL` | No | `grok-4-fast` | Default Grok model. |
| `TAVILY_API_KEY` | No | - | One Tavily key. |
| `TAVILY_API_KEYS` | No | - | Keys separated by commas, semicolons, or newlines; takes precedence over the single key. |
| `TAVILY_API_URL` | No | `https://api.tavily.com` | Tavily API root. |
| `TAVILY_ENABLED` | No | `true` | Enables or disables Tavily. |
| `TAVILY_KEY_COOLDOWN` | No | `30` | Cooldown in seconds for temporary per-key failures or rate limits. |
| `TAVILY_QUOTA_COOLDOWN` | No | `3600` | Default cooldown in seconds for exhausted quotas. |
| `TAVILY_SERVICE_FAILURE_THRESHOLD` | No | `2` | Distinct keys with the same failure required to open the service circuit; minimum 2. |
| `TAVILY_SERVICE_COOLDOWN` | No | `30` | Tavily service circuit cooldown in seconds. |
| `GROK_DEBUG` | No | `false` | Enables debug logging. |
| `GROK_LOG_LEVEL` | No | `INFO` | Log level. |
| `GROK_LOG_DIR` | No | `logs` | Log directory. |
| `GROK_RETRY_MAX_ATTEMPTS` | No | `3` | Grok retry setting. |
| `GROK_RETRY_MULTIPLIER` | No | `1` | Exponential backoff multiplier. |
| `GROK_RETRY_MAX_WAIT` | No | `10` | Maximum backoff in seconds. |

With Grok alone, `web_search` remains available. Setting `TAVILY_ENABLED=false` disables Tavily even when keys are present.

## Tool overview

| Tool | Purpose | Main response fields |
| --- | --- | --- |
| `web_search` | Grok search with optional Tavily sources | `session_id`, `content`, `sources_count`, `error` |
| `get_sources` | Retrieve all cached sources for one search | `session_id`, `sources`, `sources_count`, `error` |
| `web_fetch` | Extract Markdown with Tavily Extract | `url`, `content`, `provider`, `error` |
| `web_map` | Discover site URLs with Tavily Map | `base_url`, `results`, `response_time`, `error` |
| `get_config_info` | Return masked configuration and test Grok | `configuration`, `connection_test` |
| `switch_model` | Persist the default Grok model | `success`, `previous_model`, `current_model` |

`query` is the only required `web_search` argument. Planning tools are optional, and every `thought` argument is optional.

## Multiple Tavily keys

Configure keys with commas, semicolons, or newlines:

```text
TAVILY_API_KEYS=tvly-key-1,tvly-key-2,tvly-key-3
```

Healthy keys are selected fairly in round-robin order, and Search, Extract, and Map share the same runtime health state:

- `healthy`: participates in normal rotation.
- `cooldown`: temporary rate limit, timeout, network error, or transient service failure.
- `quota_exhausted`: unavailable for a longer quota cooldown.
- `invalid`: revoked or unauthorized and disabled for the process lifetime.

HTTP 401/403 disables the current key. HTTP 429 is classified using Tavily error data, response text, and `Retry-After`. HTTP 400/422 returns immediately without consuming every key, while HTTP 404 reports an API URL/version configuration problem. Matching 5xx or network failures from distinct keys open a service-level circuit breaker; after cooldown, only one half-open probe is allowed.

When every key is unavailable, `web_fetch` and `web_map` return `tavily_all_keys_unavailable` with masked key states. `web_search` preserves any Grok answer but sets `partial=true` and includes `tavily_error`. Only the current tool call fails; the MCP process remains alive.

## Troubleshooting

- If tools are missing, ensure `uvx` is available to the client process and validate the JSON/TOML configuration.
- If search works but fetch or map fails, configure Tavily and confirm that it is enabled.
- For corporate certificate errors, add `--native-tls` before `--from` in the `uvx` arguments.
- Configuration diagnostics mask API keys. Never commit real keys or paste them into issues and screenshots.

## Development

```bash
git clone https://github.com/Timmyzzo/WebSearch-MCP
cd WebSearch-MCP
uv sync --extra dev
uv run ruff check .
uv run pytest
uv run python -m build
```

See the [developer guide](./DEVELOPMENT.md) for module ownership, tests, and phase boundaries.

## License

[MIT License](../LICENSE)
