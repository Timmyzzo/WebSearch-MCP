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
GROK_FALLBACK_MODEL=grok-3-mini
GROK_MODEL_MAX_ATTEMPTS=3
```

Add `TAVILY_API_KEY` for page extraction, site mapping, and supplemental sources. Use `TAVILY_API_KEYS=key-1,key-2` for multiple keys.

If `GROK_PRIMARY_MODEL` is empty or unset, the compatibility variable `GROK_MODEL` is used before the persisted setting and `grok-4-fast`. The fallback is optional; identical primary/fallback IDs are not called twice. Each distinct model receives at most three real requests by default.

Optional reliability settings are `TAVILY_KEY_COOLDOWN=30`, `TAVILY_QUOTA_COOLDOWN=3600`, `TAVILY_SERVICE_FAILURE_THRESHOLD=2`, and `TAVILY_SERVICE_COOLDOWN=30`. The defaults are appropriate for most setups.

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
        "GROK_FALLBACK_MODEL": "grok-3-mini",
        "GROK_MODEL_MAX_ATTEMPTS": "3",
        "TAVILY_API_KEYS": "tvly-key-1,tvly-key-2"
      }
    }
  }
}
```

Restart the server and confirm that `web_search`, `web_fetch`, and `web_map` are present.

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
    "GROK_FALLBACK_MODEL": "grok-3-mini",
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
    "GROK_FALLBACK_MODEL": "grok-3-mini",
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
tool_timeout_sec = 180

[mcp_servers.grok-search.env]
GROK_API_URL = "https://your-api-endpoint.example/v1"
GROK_API_KEY = "your-grok-api-key"
GROK_PRIMARY_MODEL = "grok-4-fast"
GROK_FALLBACK_MODEL = "grok-3-mini"
GROK_MODEL_MAX_ATTEMPTS = "3"
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

1. Call `get_config_info` and confirm that keys are masked and Grok `/models` is reachable.
2. Call `web_search` for a recent topic.
3. Pass its `session_id` to `get_sources`.
4. Extract a public page with `web_fetch`.
5. Map a small documentation site with `web_map` and `max_depth=1`.

## 7. Troubleshooting

| Symptom | What to check |
| --- | --- |
| Server will not start | Ensure `uvx` is on the client PATH and verify the repository and command names. |
| Startup timeout | The first run may download dependencies; increase the startup timeout. |
| Invalid JSON | Check quotes and trailing commas; use a PowerShell here-string on Windows. |
| Grok connection failure | Verify the API root and `/models` support. |
| Both Grok models fail | Inspect structured `grok_error` attempt counts and classification; authentication and request errors do not switch models. |
| Fetch or map configuration error | Configure Tavily and ensure `TAVILY_ENABLED` is not `false`. |
| Certificate verification failure | Add `--native-tls` or inspect the corporate proxy certificate. |

Never commit real API keys or paste them into public issues.
