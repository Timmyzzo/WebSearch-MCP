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
- P3 Grok primary/fallback models and retries: complete.
- P4 unified response protocol: complete.
- P5 search prompt and quality work: complete.
- Next: P6 real cross-client acceptance testing.

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
    "GROK_PRIMARY_MODEL": "grok-4-fast",
    "GROK_FALLBACK_MODEL": "grok-3-mini",
    "GROK_MODEL_MAX_ATTEMPTS": "3",
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
| `GROK_PRIMARY_MODEL` | No | See below | Primary model used first for every Grok search. |
| `GROK_FALLBACK_MODEL` | No | Unset | Fallback used after the primary model fails. |
| `GROK_MODEL_MAX_ATTEMPTS` | No | `3` | Maximum real requests per distinct model; must be positive. |
| `GROK_MODEL` | No | `grok-4-fast` | Compatibility setting mapped to the primary model when `GROK_PRIMARY_MODEL` is empty or unset. |
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
| `GROK_RETRY_MULTIPLIER` | No | `1` | Exponential backoff multiplier. |
| `GROK_RETRY_MAX_WAIT` | No | `10` | Maximum backoff in seconds. |

With Grok alone, `web_search` remains available. Setting `TAVILY_ENABLED=false` disables Tavily even when keys are present.

Primary-model precedence is: a model selected by `switch_model` in the current process, non-empty `GROK_PRIMARY_MODEL`, non-empty `GROK_MODEL`, the persisted primary model, then `grok-4-fast`. Whitespace-only environment values are treated as unset. An empty or missing fallback disables switching. If the normalized primary and fallback IDs are equal, only one primary attempt group runs.

## Tool overview

| Tool | Purpose | Tool-specific fields |
| --- | --- | --- |
| `web_search` | Grok search with optional Tavily evidence synthesis | `session_id`, `content`, `sources_count`, `grok_error`, `tavily_error` |
| `get_sources` | Retrieve all cached sources for one search | `session_id`, `sources`, `sources_count` |
| `web_fetch` | Extract Markdown with Tavily Extract | `url`, `content`, `provider`, `tavily_error` |
| `web_map` | Discover site URLs with Tavily Map | `base_url`, `results`, `response_time`, `tavily_error` |
| `get_config_info` | Return masked configuration and test Grok | `configuration`, `connection_test` |
| `switch_model` | Persist and select the primary Grok model | `success`, `previous_model`, `current_model` |

Every tool also returns `status`, `error`, `error_detail`, and `partial`. `query` is the only required `web_search` argument. Planning tools are optional, and every `thought` argument is optional.

## Search quality and dynamic depth

P5 classifies each `web_search` by complexity, freshness, and risk, then applies a bounded search depth:

- `fast`: only explicit, low-ambiguity facts, usually 1–2 targeted searches.
- `standard`: clearly bounded requests such as one official document, usually 2–4 targeted searches.
- `deep`: the default for general research, freshness, people/organization profiles, records and awards, comparisons, high-risk, complex technical, niche, or contested questions; usually 4–8 multi-angle searches.

These are bounded prompt budgets, not an autonomous unbounded tool loop. Ambiguous-entity research expands aliases, accounts, organizations, teams, collaborators, events, and date ranges, then separates directly confirmed, strongly supported, plausible, conflicting, and rejected links with explainable confidence. Missing one direct identity-binding page does not stop the investigation, but inference is not presented as fact. The query and platform focus are passed as JSON data; instructions in user input, pages, or search snippets cannot override the system search rules.

When `extra_sources>0`, Tavily first supplies structured URL, title, and snippet candidates. Grok then combines those leads with its own web search for verification and final synthesis. Candidates remain untrusted evidence. A Tavily failure still permits a Grok `partial_success`, while Tavily can never replace a failed Grok answer.

The general source hierarchy is: official documentation/standards/laws/original data/papers and systematic reviews; authoritative institutions and maintainers; fact-checked professional media; professional practice; then blogs, forums, and social-media leads. High-tier sources support key conclusions, repeated syndication is not independent evidence, and insufficient evidence is stated explicitly.

Domain policies include:

- Software and GitHub: prefer current default-branch docs, README, releases, changelog, migration guides, API references, commits, issues, pull requests, and maintainer statements; verify stable versions, dates, deprecations, and merged code.
- Fitness, health, nutrition, and recovery: separate research support, expert practice, and athlete experience; account for training age, injury, baseline, recovery, equipment, and training phase; state the medical-assessment boundary for injury, disease, drugs, or extreme diets.
- Vehicle and other high-risk safety: prefer official tests and real-world incident data, separate crash avoidance from occupant protection, avoid comparing incompatible rating protocols, and explain statistical limits and uncertainty.
- Niche, ambiguous, or evidence-sparse questions: define concepts, use synonyms or other languages when useful, seek counterexamples, failures, and competing schools, and cross-check key claims with two independent source types where possible.

Queries such as “latest,” “current,” “today,” “current version,” or “still supported” use the actual runtime date and timezone and verify versions, release dates, and update times. Complex answers explain evidence level, disputes, limits, scope, and uncertainty when useful; simple answers are not forced into a long template. The P4 `success`, `partial_success`, `error`, `error_detail`, and compatibility fields remain unchanged.

## Unified response protocol

`status` has exactly three stable values:

- `success`: the tool goal completed. An empty source list is valid when Grok returned a real answer without citations.
- `partial_success`: useful output is available, but a supplemental component or non-critical step failed. Examples include Grok succeeding while Tavily fails, an incomplete planning session, or a site map with ignored invalid entries.
- `error`: the tool goal did not complete. Empty answers, empty extracted content, empty URL maps, configuration errors, and upstream failures never masquerade as success.

| Tool | `success` | `partial_success` | `error` and empty results |
| --- | --- | --- | --- |
| `web_search` | Grok returns a non-empty valid answer; sources may be empty. | Grok succeeds but requested Tavily supplementation fails. | Final Grok failure, interrupted stream, invalid/empty answer, or configuration failure; Tavily cannot replace the Grok answer. |
| `get_sources` | The session exists; `sources=[]` is a valid empty result. | Only part of the cached source data validates. | Missing/expired session or cache-component failure. |
| `web_fetch` | Tavily returns non-empty Markdown. | Single-URL extraction is atomic, so partial success is not currently applicable. | Configuration, authentication, rate limit, service, request errors, or `tavily_no_content` after a successful empty upstream result. |
| `web_map` | At least one URL is returned and the response is complete. | URLs are available, but the base URL is missing or invalid entries were ignored. | Tavily failure or `tavily_no_urls` after a successful empty upstream result. |
| `get_config_info` | Masked configuration and the Grok connection test both succeed. | Configuration is usable, but connectivity/authentication/config validation fails. | Even the masked configuration object cannot be built. |
| `switch_model` | The primary model is written to the process and compatibility config. | The write is atomic, so partial success is not currently applicable. | Empty model or persistence failure; it still changes only the primary model. |
| Planning tools | Required phases are complete and an executable plan exists. | The session is valid but required phases remain. | Missing session, invalid JSON parameters, or planning-component failure. |

The canonical error object is `error_detail`:

```json
{
  "code": "tavily_service_unavailable",
  "message": "Tavily is temporarily unavailable",
  "service": "tavily",
  "retryable": true,
  "http_status": 503,
  "upstream_code": "upstream_unavailable",
  "diagnostics": {
    "service_circuit": {"state": "open", "retry_after_seconds": 30}
  }
}
```

Diagnostics contain only necessary redacted data. They exclude Grok and Tavily keys, Authorization headers, response bodies that may echo credentials, Python tracebacks, and internal object representations. A structured error ends only the current call; the stdio MCP process remains available for discovery and later calls.

Compatibility mapping:

| Legacy field | P4 mapping |
| --- | --- |
| `error` | Preserved as the legacy string code or message. New callers should read `error_detail`. |
| `partial` | `true` when `status="partial_success"`; otherwise defaults to `false`. |
| `tavily_error` | Preserves P2 key-state and service-circuit summaries and adds retry/HTTP/upstream fields. |
| `grok_error` | Preserves P3 model names, real attempt counts, final classification, and switch state. |
| `content`, `results`, `success` | Preserved per tool; use `status` as the authoritative outcome. |

Typical responses follow.

`web_search` succeeds even when a valid answer has no sources:

```json
{"status":"success","session_id":"abc123","content":"A valid answer","sources_count":0,"error":null,"error_detail":null,"partial":false}
```

Grok succeeds but supplemental Tavily search fails:

```json
{"status":"partial_success","session_id":"abc123","content":"A valid answer","sources_count":0,"partial":true,"error":null,"error_detail":{"code":"tavily_all_keys_unavailable","message":"All Tavily keys are unavailable","service":"tavily","retryable":false,"http_status":401,"upstream_code":"invalid_api_key","diagnostics":{"key_statuses":[{"fingerprint":"tvly…1234","state":"invalid"}]}},"tavily_error":{"code":"tavily_all_keys_unavailable","message":"All Tavily keys are unavailable"}}
```

If Grok ultimately fails, successful Tavily results never become a fake Grok answer:

```json
{"status":"error","session_id":"abc123","content":"","sources_count":0,"error":"grok_primary_and_fallback_failed","error_detail":{"code":"grok_primary_and_fallback_failed","message":"Both Grok models are unavailable","service":"grok","retryable":true,"http_status":503,"upstream_code":"upstream_unavailable","diagnostics":{"primary_attempts":3,"fallback_attempts":3,"total_attempts":6}},"partial":false}
```

Other tool examples:

```jsonl
{"tool":"get_sources","status":"success","session_id":"abc123","sources":[],"sources_count":0}
{"tool":"web_fetch","status":"success","url":"https://example.com","content":"# Page","provider":"tavily"}
{"tool":"web_map","status":"error","base_url":"https://example.com","results":[],"error_detail":{"code":"tavily_no_urls","message":"Tavily succeeded but found no URLs","service":"tavily","retryable":false,"http_status":null,"upstream_code":null,"diagnostics":{"upstream_succeeded":true,"empty_result":true}}}
{"tool":"get_config_info","status":"partial_success","partial":true,"configuration":{"GROK_API_KEY":"not configured"},"connection_test":{"status":"configuration error"},"error_detail":{"code":"grok_configuration_error","message":"GROK_API_KEY is not configured","service":"grok","retryable":false,"http_status":null,"upstream_code":null,"diagnostics":{"configuration":"grok"}}}
{"tool":"switch_model","status":"success","success":true,"previous_model":"grok-4-fast","current_model":"grok-3-mini","message":"Primary model changed"}
{"tool":"plan_intent","status":"partial_success","partial":true,"session_id":"plan123","plan_complete":false,"phases_remaining":["complexity_assessment","query_decomposition"],"error_detail":{"code":"planning_incomplete","message":"The search plan is incomplete","service":"planning","retryable":true,"http_status":null,"upstream_code":null,"diagnostics":{"phases_remaining":["complexity_assessment","query_decomposition"]}}}
```

## Grok primary/fallback models and retries

Each call starts with the primary model. HTTP 408, 429, 5xx, connection failures, connect/read timeouts, interrupted streams, and recognizable relay errors such as unavailable/dead upstream accounts or an unavailable account pool are retried with jittered exponential backoff. Each distinct model receives at most `GROK_MODEL_MAX_ATTEMPTS` real requests. The fallback has an independent counter, is selected at most once, and never loops back to the primary.

Model-not-found, model-permission, and model-temporarily-unavailable errors stop attempts for that model and switch early. Explicit 400/422 request errors and 401/403 or explicit API-key authentication failures stop immediately without retrying or switching. Classification combines the HTTP status with OpenAI-compatible error objects, codes, types, and response semantics.

Stream content is buffered until a valid completion signal. Partial content from an interrupted stream is never returned as a complete answer, cached, or used to extract sources. Final failures include a structured `grok_error` with both model names, per-model and total attempt counts, the last classification, HTTP/upstream code, and whether switching occurred. API keys and Authorization values are excluded. Successful Tavily results never masquerade as a complete Grok answer, and only the current MCP tool call ends.

`switch_model(model)` keeps its original call shape but now explicitly changes the primary model. It updates the active process and persists `primary_model` plus the legacy `model` field. It never changes `GROK_FALLBACK_MODEL`.

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

When every key is unavailable, `web_fetch` and `web_map` return `status="error"`, `tavily_all_keys_unavailable`, and masked key states. `web_search` preserves any Grok answer with `status="partial_success"`, `partial=true`, and `tavily_error`. Only the current tool call ends; the MCP process remains alive.

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
