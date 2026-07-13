<div align="center">

English | [简体中文](../README.md)

A standard MCP web-search server for Cherry Studio, Claude Code, and Codex

**Deep research · active 270-second budget · Grok concurrency 2 · one Tavily request per key**

[![CI](https://github.com/Timmyzzo/WebSearch-MCP/actions/workflows/ci.yml/badge.svg)](https://github.com/Timmyzzo/WebSearch-MCP/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](../LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![MCP stdio](https://img.shields.io/badge/MCP-stdio-green.svg)](https://modelcontextprotocol.io/)

</div>

<p align="center">
  <a href="#quick-start">Quick start</a> ·
  <a href="#why-websearch-mcp">Highlights</a> ·
  <a href="#tool-overview">Tools</a> ·
  <a href="#configuration">Configuration</a> ·
  <a href="./CLIENT_SETUP_EN.md">Client setup</a>
</p>

## What is WebSearch MCP?

WebSearch MCP combines Grok's AI-powered web search with Tavily search, page extraction, and site mapping behind a standard MCP stdio server. It does not depend on private client capabilities and never edits local Cherry Studio, Claude Code, or Codex configuration.

```text
MCP Client --stdio--> WebSearch MCP
                       |-- web_search --> Grok /v1/chat/completions + optional Tavily sources
                       |-- get_sources --> cached search sources
                       |-- web_fetch  --> Tavily Extract
                       `-- web_map    --> Tavily Map
```

## Why WebSearch MCP

| Capability | Observable behavior |
| --- | --- |
| Deep by default | Every search covers at least five independent perspectives and deep-dives into two, usually producing 7–12 retrieval actions. |
| Strong-model first | One user-selected Grok model is used throughout, with up to twelve real attempts by default. |
| Single upstream protocol | Calls only OpenAI-compatible `/v1/chat/completions`; Responses and automatic protocol switching are disabled. |
| Evidence fusion | Tavily candidates enter the same Grok verification and synthesis request. |
| Explainable reliability | A roughly 270-second server budget, process-wide Grok concurrency of two, one request per Tavily key, circuits, `Retry-After`, and complete-stream validation. |
| Stable compatibility | Standard MCP stdio, fixed tool schemas, and three stable outcome states. |

Typical uses include retrieving current official documentation, producing answers with traceable sources, extracting pages as Markdown, and reusing the same web tools across MCP clients.

## Project status

- P0 repository and test baseline: complete.
- P1 legacy crawler removal and modularization: complete.
- P2 Tavily multi-key reliability: complete.
- P3 Grok single-model reliability and retries: complete.
- P4 unified response protocol: complete.
- P5 search prompt and quality work: complete.
- Search timeout and concurrency governance: automated implementation complete; Cherry Studio acceptance at a 300-second outer timeout remains.
- External code audit and bounded runtime caches: complete; runtime traffic is Chat Completions only.
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
    "GROK_MODEL_MAX_ATTEMPTS": "5",
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
| `GROK_PRIMARY_MODEL` | No | See below | Strong model selected by the user for every Grok search. |
| `GROK_MODEL_MAX_ATTEMPTS` | No | `12` | Maximum real requests for recoverable failures on the current model; any positive integer is accepted. |
| `GROK_MAX_CONCURRENCY` | No | `2` | Maximum concurrent Grok `/chat/completions` requests in one MCP process; the safety ceiling is two. |
| `WEB_SEARCH_TOTAL_TIMEOUT` | No | `270` | Total server-side wall-clock budget for one `web_search`, in seconds. |
| `GROK_SINGLE_ATTEMPT_TIMEOUT` | No | `120` | Per-attempt stream read limit, clipped to the remaining total budget. |
| `GROK_RETRY_MULTIPLIER` | No | `1` | Initial exponential-backoff multiplier; accepts non-negative numbers. |
| `GROK_RETRY_MAX_WAIT` | No | `10` | Maximum delay for one backoff; accepts non-negative numbers. |
| `GROK_RETRYABLE_UPSTREAM_CODES` | No | See below | Retryable codes embedded in HTTP 200 error bodies; comma, semicolon, or newline separated. |
| `GROK_MODEL` | No | `grok-4-fast` | Compatibility setting mapped to the primary model when `GROK_PRIMARY_MODEL` is empty or unset. |
| `TAVILY_API_KEY` | No | - | One Tavily key. |
| `TAVILY_API_KEYS` | No | - | Keys separated by commas, semicolons, or newlines; takes precedence over the single key. |
| `TAVILY_API_URL` | No | `https://api.tavily.com` | Tavily API root. |
| `TAVILY_ENABLED` | No | `true` | Enables or disables Tavily. |
| `TAVILY_KEY_COOLDOWN` | No | `30` | Cooldown in seconds for temporary per-key failures or rate limits. |
| `TAVILY_QUOTA_COOLDOWN` | No | `3600` | Default cooldown in seconds for exhausted quotas. |
| `TAVILY_SERVICE_FAILURE_THRESHOLD` | No | `2` | Distinct keys with the same failure required to open the service circuit; minimum 2. |
| `TAVILY_SERVICE_COOLDOWN` | No | `30` | Tavily service circuit cooldown in seconds. |
| `TAVILY_PER_KEY_MAX_CONCURRENCY` | No | `1` | Shared Search/Extract/Map concurrency per key; currently required to be one. |
| `GROK_DEBUG` | No | `false` | Enables debug logging. |
| `GROK_LOG_LEVEL` | No | `INFO` | Log level. |
| `GROK_LOG_DIR` | No | `logs` | Log directory. |

With Grok alone, `web_search` remains available. Setting `TAVILY_ENABLED=false` disables Tavily even when keys are present.

Model precedence is: a model selected by `switch_model` in the current process, non-empty `GROK_PRIMARY_MODEL`, non-empty `GROK_MODEL`, the persisted model, then `grok-4-fast`. Whitespace-only values are treated as unset. The server does not downgrade to a weaker fallback model.

The default HTTP-200 retry codes are `rate_limit`, `rate_limit_exceeded`, `too_many_requests`, `upstream_error`, `server_error`, `service_unavailable`, `temporarily_unavailable`, `overloaded`, `overloaded_error`, and `internal_error`. Setting `GROK_RETRYABLE_UPSTREAM_CODES` replaces this list, so retain any defaults that should continue to retry when adding provider-specific codes.

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

## Search quality and deep-first execution

Every `web_search` uses a bounded `deep` profile: search at least five genuinely different perspectives, then investigate at least two of the most relevant or uncertain perspectives further. Normal requests therefore use roughly 7–12 retrieval actions; ambiguous entities, current events, comparisons, high-risk, niche, and contested questions usually use 10–16. Simple facts and single official-document requests keep the same floor while their final answers remain concise.

This floor matches the validated reference project's requirement of 5+ breadth perspectives and at least two depth investigations. WebSearch MCP adds deterministic budgets, native/entity-language searches, source hierarchy, counterevidence, and Tavily evidence synthesis. Minor wording variants do not count as separate perspectives, and source quantity never replaces quality.

These are bounded prompt budgets, not an autonomous unbounded tool loop. Ambiguous-entity research expands aliases, accounts, organizations, teams, collaborators, events, and date ranges, then separates directly confirmed, strongly supported, plausible, conflicting, and rejected links with explainable confidence. Missing one direct identity-binding page does not stop the investigation, but inference is not presented as fact. The query and platform focus are passed as JSON data; instructions in user input, pages, or search snippets cannot override the system search rules.

When `extra_sources>0`, Tavily first supplies structured URL, title, and snippet candidates. Grok then combines those leads with its own web search for verification and final synthesis. Candidates remain untrusted evidence. A Tavily failure still permits a Grok `partial_success`, while Tavily can never replace a failed Grok answer.

The upstream protocol is fixed to streaming Chat Completions. The server does not read a protocol-selection variable, call `/responses`, or switch endpoints after a failure; a relay only needs `/v1/chat/completions` and `/v1/models`.

The general source hierarchy is: official documentation/standards/laws/original data/papers and systematic reviews; authoritative institutions and maintainers; fact-checked professional media; professional practice; then blogs, forums, and social-media leads. High-tier sources support key conclusions, repeated syndication is not independent evidence, and insufficient evidence is stated explicitly.

Domain policies include:

- Software and GitHub: prefer current default-branch docs, README, releases, changelog, migration guides, API references, commits, issues, pull requests, and maintainer statements; verify stable versions, dates, deprecations, and merged code.
- Fitness, health, nutrition, and recovery: separate research support, expert practice, and athlete experience; account for training age, injury, baseline, recovery, equipment, and training phase; state the medical-assessment boundary for injury, disease, drugs, or extreme diets.
- Vehicle and other high-risk safety: prefer official tests and real-world incident data, separate crash avoidance from occupant protection, avoid comparing incompatible rating protocols, and explain statistical limits and uncertainty.
- Niche, ambiguous, or evidence-sparse questions: define concepts, use synonyms or other languages when useful, seek counterexamples, failures, and competing schools, and cross-check key claims with two independent source types where possible.

Queries such as “latest,” “current,” “today,” “current version,” or “still supported” use the actual runtime date and timezone and verify versions, release dates, and update times. Complex answers explain evidence level, disputes, limits, scope, and uncertainty when useful; simple answers are not forced into a long template. The P4 `success`, `partial_success`, `error`, `error_detail`, and compatibility fields remain unchanged.

## Timeout and concurrency governance

Set Cherry Studio's outer MCP tool timeout to 300 seconds. This is a safety ceiling that prevents an early bare `-32001`, not a latency target. Each `web_search` uses `WEB_SEARCH_TOTAL_TIMEOUT=270` by default and actively returns success, partial success, or a structured error within that server-side wall-clock budget, leaving roughly 30 seconds for MCP serialization, scheduling, transport, and client-side variance.

The per-attempt Grok read limit is controlled by `GROK_SINGLE_ATTEMPT_TIMEOUT`, defaulting to 120 seconds, and is clipped to the remaining total budget. `GROK_MODEL_MAX_ATTEMPTS=12` means at most twelve real HTTP requests, not twelve guaranteed requests. Grok-slot waits, Tavily-key waits, HTTP and stream time, exponential backoff, and `Retry-After` all consume the same total budget. A new retry is not started when the remaining budget is no longer reasonable for another attempt.

One MCP process runs at most two Grok HTTP requests by default. Tavily Search, Extract, and Map share key health and occupancy, with at most one real request on each key; distinct healthy keys can run concurrently. Success, failure, cancellation, timeout, and interrupted-stream paths release their slots, and every retry must queue again. Diagnostics distinguish `max_attempts_exhausted`, `non_retryable_error`, `total_budget_exhausted`, and `concurrency_queue_timeout`, with configured/actual attempts, elapsed time, budget, and queue wait.

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
{"status":"error","session_id":"abc123","content":"","sources_count":0,"error":"grok_primary_failed","error_detail":{"code":"grok_primary_failed","message":"The Grok model failed after exhausting the maximum attempts","service":"grok","retryable":true,"http_status":503,"upstream_code":"upstream_unavailable","diagnostics":{"primary_attempts":5,"fallback_attempts":0,"total_attempts":5,"termination_reason":"max_attempts_exhausted","configured_max_attempts":5,"actual_attempts":5,"elapsed_ms":120000,"budget_ms":270000,"queue_wait_ms":0}},"partial":false}
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

## Grok protocol and one strong model with up to twelve real attempts

The service uses streaming Chat Completions only. OpenRouter keeps the compatible `:online` model suffix, and every retry stays on the same `/v1/chat/completions` endpoint and current model.

Each call uses only the configured model. HTTP 408, 429, 5xx, connection failures, connect/read timeouts, interrupted streams, recognizable relay account-pool failures, and configured temporary codes inside HTTP 200 error bodies are retried with jittered exponential backoff, up to twelve real requests by default.

Retries cannot exceed `WEB_SEARCH_TOTAL_TIMEOUT` or bypass `GROK_MAX_CONCURRENCY`. Authentication, request, missing-model, and permission errors say that execution stopped early because the failure was not retryable. Only a call that really reaches the configured limit reports exhausted maximum attempts. Total-budget and concurrency-queue exhaustion have distinct structured reasons.

Model-not-found and model-permission errors stop immediately; temporary model unavailability retries the same model. Explicit 400/422 request errors and 401/403 or explicit API-key authentication failures also stop immediately.

Stream content is buffered until a valid completion signal. Partial content from an interrupted stream is never returned, cached, or used to extract sources. Final failures report the current model and real attempt count while preserving legacy fallback fields as `null`, `0`, and `false`. API keys and Authorization values are excluded.

`switch_model(model)` keeps its original call shape, updates the active model, and persists `primary_model` plus the legacy `model` field.

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

Busy is transient occupancy, separate from key health, and is never reclassified as cooldown, quota exhaustion, or invalidity. A request prefers another healthy idle key; if every healthy key is busy, it waits for the earliest slot within the current tool budget.

HTTP 401/403 disables the current key. HTTP 429 is classified using Tavily error data, response text, and `Retry-After`. HTTP 400/422 returns immediately without consuming every key, while HTTP 404 reports an API URL/version configuration problem. Matching 5xx or network failures from distinct keys open a service-level circuit breaker; after cooldown, only one half-open probe is allowed.

When every key is unavailable, `web_fetch` and `web_map` return `status="error"`, `tavily_all_keys_unavailable`, and masked key states. `web_search` preserves any Grok answer with `status="partial_success"`, `partial=true`, and `tavily_error`. Only the current tool call ends; the MCP process remains alive.

## Bounded runtime caches

Source sessions live only in the current MCP process, with at most 256 entries and a one-hour TTL. `get_sources` returns `session_id_not_found_or_expired` for expired sessions. Successful model catalogs are cached for five minutes before `/models` is refreshed; failures are not cached as empty catalogs. Final answers are not cached long term, and full search bodies are not written to disk by default.

## Troubleshooting

- If tools are missing, ensure `uvx` is available to the client process and validate the JSON/TOML configuration.
- If search works but fetch or map fails, configure Tavily and confirm that it is enabled.
- For corporate certificate errors, add `--native-tls` before `--from` in the `uvx` arguments.
- Configuration diagnostics mask API keys. Never commit real keys or paste them into issues and screenshots.
- If Cherry Studio still reports `-32001`, set its MCP tool timeout to 300 seconds and keep the server budget below it; the default is 270 seconds. The 300-second value is a safety ceiling, not a performance goal.

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

See the [external implementation analysis](./EXTERNAL_PROJECT_ANALYSIS.md) for the code-level comparison, license boundaries, and accepted/rejected designs.

## License

[MIT License](../LICENSE)
