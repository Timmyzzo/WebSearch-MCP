# WebSearch MCP client setup

This guide covers standard MCP stdio configuration for Cherry Studio, Claude Code, and Codex. Every example installs from:

```text
https://github.com/Timmyzzo/WebSearch-MCP
```

## 1. Common requirements

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and ensure the client process can find `uvx`:

```bash
uvx --version
```

Minimum environment:

```text
GROK_API_URL=https://your-api-endpoint.example/v1
GROK_API_KEY=your-grok-api-key
GROK_PRIMARY_MODEL=grok-4-fast
GROK_MODEL_MAX_ATTEMPTS=5
GROK_MAX_CONCURRENCY=2
WEB_SEARCH_TOTAL_TIMEOUT=270
```

Add `TAVILY_API_KEY` for page extraction, site mapping, and supplemental sources. Use `TAVILY_API_KEYS=key-1,key-2` for multiple keys.

If `GROK_PRIMARY_MODEL` is empty or unset, the compatibility variable `GROK_MODEL` is used before the persisted setting and `grok-4-fast`. The service uses that one strong model without automatic fallback. Recoverable failures receive at most five real requests by default.

The upstream protocol is fixed to streaming `/v1/chat/completions`; `/responses` and runtime protocol switching are not supported. `GROK_API_URL` should normally end in `/v1` and also expose `/models`.

Optional reliability settings are `TAVILY_PER_KEY_MAX_CONCURRENCY=1`, `TAVILY_KEY_COOLDOWN=30`, `TAVILY_QUOTA_COOLDOWN=3600`, `TAVILY_SERVICE_FAILURE_THRESHOLD=2`, and `TAVILY_SERVICE_COOLDOWN=30`. The Grok safety ceiling is two concurrent requests, and Tavily currently requires one request per key. The defaults are appropriate for most setups.

## 2. Cherry Studio

Add a stdio MCP server:

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
        "GROK_PRIMARY_MODEL": "grok-4-fast",
        "GROK_MODEL_MAX_ATTEMPTS": "5",
        "GROK_MAX_CONCURRENCY": "2",
        "WEB_SEARCH_TOTAL_TIMEOUT": "270",
        "TAVILY_PER_KEY_MAX_CONCURRENCY": "1",
        "TAVILY_API_KEYS": "tvly-key-1,tvly-key-2"
      }
    }
  }
}
```

Restart the server and confirm that `web_search`, `web_fetch`, and `web_map` are present.

In Cherry Studio's advanced MCP server settings, set the tool-call timeout to **300 seconds**. This is a client-side safety ceiling, not a latency target. The server returns a business result or structured timeout within roughly 270 seconds by default, before Cherry Studio emits a bare `-32001`.

## 3. Claude Code

### Linux/macOS

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
    "GROK_PRIMARY_MODEL": "grok-4-fast",
    "TAVILY_API_KEY": "tvly-your-tavily-key"
  }
}'
```

### Windows PowerShell

Use a here-string to avoid JSON quoting problems:

```powershell
$config = @'
{
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
    "GROK_PRIMARY_MODEL": "grok-4-fast",
    "TAVILY_API_KEY": "tvly-your-tavily-key"
  }
}
'@

claude mcp remove grok-search
claude mcp add-json grok-search --scope user $config
```

Verify with:

```bash
claude mcp list
```

## 4. Codex

Add this to `~/.codex/config.toml`:

```toml
[mcp_servers.grok-search]
command = "uvx"
args = [
  "--from",
  "git+https://github.com/Timmyzzo/WebSearch-MCP",
  "grok-search",
]
startup_timeout_sec = 30
tool_timeout_sec = 300

[mcp_servers.grok-search.env]
GROK_API_URL = "https://your-api-endpoint.example/v1"
GROK_API_KEY = "your-grok-api-key"
GROK_PRIMARY_MODEL = "grok-4-fast"
GROK_MODEL_MAX_ATTEMPTS = "5"
GROK_MAX_CONCURRENCY = "2"
WEB_SEARCH_TOTAL_TIMEOUT = "270"
TAVILY_PER_KEY_MAX_CONCURRENCY = "1"
TAVILY_API_KEYS = "tvly-key-1,tvly-key-2"
```

Restart the Codex session and confirm that the MCP server exposes the core tools.

## 5. Corporate networks and proxies

For certificate-chain errors, add `--native-tls` before `--from`:

```json
"args": [
  "--native-tls",
  "--from",
  "git+https://github.com/Timmyzzo/WebSearch-MCP",
  "grok-search"
]
```

Proxy settings such as `HTTP_PROXY`, `HTTPS_PROXY`, and `NO_PROXY` can be supplied in the MCP environment.

## 6. Acceptance steps

1. Call `get_config_info` and confirm that keys are masked. A healthy connection returns `success`; a failed connection test with usable configuration returns `partial_success` and `error_detail`.
2. Call `web_search` for a recent topic and confirm that a complete result has `status="success"`.
3. Pass its `session_id` to `get_sources`. A valid session with no citations still returns `success` with an empty `sources` array.
4. Extract a public page with `web_fetch`. If the upstream request succeeds but the page has no content, expect `error`/`tavily_no_content`, distinct from configuration or service failures.
5. Map a small documentation site with `web_map` and `max_depth=1`. A legitimate empty map returns `error`/`tavily_no_urls`.
6. After a structured error, list or call tools again and confirm that the MCP process remains alive.
7. Start two concurrent `web_search` calls and then a third; confirm that the third queues and all three return a business result or structured error within 300 seconds.
8. Confirm that `grok_error.termination_reason`, configured/actual attempts, elapsed time, budget, and queue wait match the observed behavior.

The canonical error object is `error_detail`, with at least `code`, `message`, `service`, and `retryable`; it also includes `http_status`, `upstream_code`, and redacted `diagnostics` when available. Legacy `error`, `partial`, `tavily_error`, and `grok_error` fields remain available.

Keep the timeout hierarchy as: 300-second client tool timeout > 270-second server `web_search` budget > 120-second Grok read limit per attempt. Maximum attempts, concurrency waits, HTTP/stream time, backoff, and `Retry-After` share the same 270-second budget, so “up to five” does not guarantee five requests. One process permits at most two Grok requests by default. Tavily Search, Extract, and Map share a one-request-per-key limit, while distinct healthy keys may run concurrently.

P5 adds no client parameters or response fields. Every `web_search` covers at least five independent perspectives and deep-dives into two. Normal requests usually use 7–12 retrieval actions; ambiguous entities, current events, comparisons, high-risk, niche, and contested questions usually use 10–16. Queries expand across their native language and relevant entity languages. With `extra_sources>0`, Tavily candidates enter Grok's final synthesis.

Source sessions retain at most 256 entries and expire after one hour. Successful model catalogs are cached for five minutes. Expiration affects only `get_sources` or model validation; public tool parameters and the P4 response schema do not change.

## 7. Troubleshooting

| Symptom | What to check |
| --- | --- |
| Server will not start | Ensure `uvx` is on the client PATH and verify the repository and command names. |
| Startup timeout | The first run may download dependencies; increase the startup timeout. |
| Invalid JSON | Check quotes and trailing commas; use a PowerShell here-string on Windows. |
| Grok connection failure | Verify the API root and `/models` support. |
| The Grok model ultimately fails | Inspect `error_detail` first, then the compatible `grok_error` attempt count and classification; authentication, request, missing-model, and permission errors stop immediately. |
| Cherry Studio reports `-32001` | Set the MCP tool timeout to 300 seconds and keep `WEB_SEARCH_TOTAL_TIMEOUT` at 270 seconds or lower. |
| Fetch or map configuration error | Configure Tavily and ensure `TAVILY_ENABLED` is not `false`. |
| Client displays partial success | Inspect `status="partial_success"`, `error_detail`, and the component compatibility field; the usable result is still available. |
| Certificate verification failure | Add `--native-tls` or inspect the corporate proxy certificate. |

Never commit real API keys or paste them into public issues.
