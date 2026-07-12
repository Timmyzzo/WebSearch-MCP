![WebSearch MCP](./images/title.png)

<div align="center">

[English](./docs/README_EN.md) | 简体中文

面向 Cherry Studio、Claude Code 与 Codex 的标准 MCP 网络搜索服务

[![CI](https://github.com/Timmyzzo/WebSearch-MCP/actions/workflows/ci.yml/badge.svg)](https://github.com/Timmyzzo/WebSearch-MCP/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![MCP stdio](https://img.shields.io/badge/MCP-stdio-green.svg)](https://modelcontextprotocol.io/)

</div>

## WebSearch MCP 是什么

WebSearch MCP 把 Grok 的 AI 联网搜索与 Tavily 的结构化检索、网页提取和站点映射组合成一个标准 MCP stdio 服务。它不依赖某个客户端的私有能力，也不会修改 Cherry Studio、Claude Code 或 Codex 的本地配置。

```text
MCP Client ──stdio──► WebSearch MCP
                       ├─ web_search ─► Grok + 可选 Tavily 信源
                       ├─ get_sources ─► 搜索信源缓存
                       ├─ web_fetch  ─► Tavily Extract
                       └─ web_map    ─► Tavily Map
```

适合以下场景：

- 让编码助手检索最新官方文档、Release、Issue 和技术资料。
- 获取带可追溯信源的实时搜索答案。
- 把网页正文提取为 Markdown，或发现文档站点的 URL 结构。
- 在多个 MCP 客户端之间复用相同工具 Schema 和环境变量。

## 当前状态

- P0 仓库与测试基线：已完成。
- P1 旧抓取服务清理与模块化：已完成。
- P2 Tavily 多 Key 可靠性：已完成。
- P3 Grok 主备模型与重试：已完成。
- 下一阶段：P4 统一返回协议。

完整需求与验收标准见 [开发路线文档](./docs/DEVELOPMENT_ROADMAP.md)。

## 快速开始

### 1. 准备环境

需要：

- Python 3.10+
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- 一个 OpenAI 兼容的 Grok API 地址和 Key
- 可选的 Tavily Key；`web_fetch`、`web_map` 和额外 Tavily 信源需要它

### 2. 添加 MCP 服务

以下是 Claude Code 的 Linux/macOS 示例：

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

Cherry Studio、Claude Code PowerShell 和 Codex 的完整配置与验证步骤见：

- [客户端配置指南（中文）](./docs/CLIENT_SETUP.md)
- [Client setup guide (English)](./docs/CLIENT_SETUP_EN.md)

### 3. 验证

在客户端中确认能发现以下核心工具：

```text
web_search
get_sources
web_fetch
web_map
get_config_info
switch_model
```

建议先调用 `get_config_info` 检查脱敏配置和 Grok `/models` 连接，再执行一次 `web_search`。

## 配置

| 变量 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `GROK_API_URL` | 是 | - | OpenAI 兼容 API 根地址，需提供 `/chat/completions` 和 `/models`。 |
| `GROK_API_KEY` | 是 | - | Grok API Key。 |
| `GROK_PRIMARY_MODEL` | 否 | 见下文 | 主模型；优先用于每次 Grok 搜索。 |
| `GROK_FALLBACK_MODEL` | 否 | 未配置 | 主模型失败后使用的备用模型。 |
| `GROK_MODEL_MAX_ATTEMPTS` | 否 | `3` | 每个不同模型最多实际请求次数，必须为正整数。 |
| `GROK_MODEL` | 否 | `grok-4-fast` | 兼容配置；未设置非空 `GROK_PRIMARY_MODEL` 时映射为主模型。 |
| `TAVILY_API_KEY` | 否 | - | 单个 Tavily Key。 |
| `TAVILY_API_KEYS` | 否 | - | 多个 Tavily Key，支持逗号、分号或换行分隔，优先于单 Key。 |
| `TAVILY_API_URL` | 否 | `https://api.tavily.com` | Tavily API 根地址。 |
| `TAVILY_ENABLED` | 否 | `true` | 是否启用 Tavily。 |
| `TAVILY_KEY_COOLDOWN` | 否 | `30` | 临时限流或单 Key 临时异常的冷却秒数。 |
| `TAVILY_QUOTA_COOLDOWN` | 否 | `3600` | 额度耗尽 Key 的默认冷却秒数。 |
| `TAVILY_SERVICE_FAILURE_THRESHOLD` | 否 | `2` | 触发服务级熔断所需的不同 Key 同类故障数，最小为 2。 |
| `TAVILY_SERVICE_COOLDOWN` | 否 | `30` | Tavily 服务级熔断冷却秒数。 |
| `GROK_DEBUG` | 否 | `false` | 是否记录调试信息。 |
| `GROK_LOG_LEVEL` | 否 | `INFO` | 日志级别。 |
| `GROK_LOG_DIR` | 否 | `logs` | 日志目录。 |
| `GROK_RETRY_MULTIPLIER` | 否 | `1` | 指数退避乘数。 |
| `GROK_RETRY_MAX_WAIT` | 否 | `10` | 单次退避最大秒数。 |

只配置 Grok 时，`web_search` 仍可使用。设置 `TAVILY_ENABLED=false` 会禁用 Tavily，即使环境中存在 Tavily Key。

主模型的解析优先级为：当前进程中 `switch_model` 设置的主模型、非空 `GROK_PRIMARY_MODEL`、非空 `GROK_MODEL`、配置文件中的主模型、默认值 `grok-4-fast`。环境变量仅包含空白时视为未设置。备用模型未配置或为空时不会切换；主备模型经规范化后相同时只执行一组主模型尝试，不会重复消耗同一模型。

## 工具概览

| 工具 | 用途 | 主要返回字段 |
| --- | --- | --- |
| `web_search` | Grok 主搜索，可选 Tavily 补充信源 | `session_id`、`content`、`sources_count`、`error`、`grok_error` |
| `get_sources` | 读取某次搜索的完整信源 | `session_id`、`sources`、`sources_count`、`error` |
| `web_fetch` | 使用 Tavily Extract 提取 Markdown | `url`、`content`、`provider`、`error` |
| `web_map` | 使用 Tavily Map 发现站点结构 | `base_url`、`results`、`response_time`、`error` |
| `get_config_info` | 查看脱敏配置并测试 Grok 连接 | `configuration`、`connection_test` |
| `switch_model` | 持久化并切换当前进程的 Grok 主模型 | `success`、`previous_model`、`current_model` |

`web_search` 的 `query` 是唯一必填参数。规划工具是可选能力，不是搜索前置步骤；所有 `thought` 参数均为可选。

## Grok 主备模型与重试

每次调用先使用主模型。408、429、5xx、连接失败、连接/读取超时、完整内容产生前或流式传输中的中断，以及可识别的中转站“上游账号不可用/死号/账号池不可用”错误，会按带随机抖动的指数退避重试。每个模型最多执行 `GROK_MODEL_MAX_ATTEMPTS` 次真实请求；主模型用尽后只切换一次备用模型，备用模型独立计数，不会在主备之间循环。

模型不存在、无权限或暂时不可用会停止当前模型的重复请求并尽快切换备用模型。明确的 400/422 参数错误和 401/403/API Key 认证失败会立即停止，不重试也不切换。错误分类同时检查 HTTP 状态、OpenAI 兼容错误对象、错误码、错误类型和正文语义。

流内容会在服务端完整缓冲并校验结束标志。流在产生部分内容后中断时，残缺内容不会作为成功答案返回、缓存或提取来源。最终失败返回 `grok_error`，包含主备模型、各自及总尝试次数、最后错误分类、状态码/上游错误码和是否切换模型；不会包含 API Key 或 Authorization 值。Tavily 即使成功也不会被伪装成完整 Grok 答案。该错误只结束当前工具调用，MCP 进程仍可继续处理后续请求。

`switch_model(model)` 保持旧调用形式不变，但语义明确为修改“主模型”：它更新当前进程使用的主模型，并将 `primary_model`（同时保留兼容的 `model` 字段）写入本地配置。它不会修改 `GROK_FALLBACK_MODEL`。

## 多 Tavily Key

可以使用逗号、分号或换行配置多个 Key：

```text
TAVILY_API_KEYS=tvly-key-1,tvly-key-2,tvly-key-3
```

正常请求会在健康 Key 间公平轮询，Search、Extract、Map 共享同一套运行时状态：

- `healthy`：正常参与轮询。
- `cooldown`：临时限流、超时、网络错误或临时服务异常，冷却后重新探测。
- `quota_exhausted`：额度耗尽，使用较长冷却时间。
- `invalid`：Key 无效或被撤销，本进程内不再使用。

401/403 会使当前 Key 失效；429 会根据错误码、正文和 `Retry-After` 区分临时限流与额度耗尽；400/422 直接返回参数错误；404 提示检查 `TAVILY_API_URL`。多个不同 Key 出现相同 5xx 或网络错误时会触发服务级熔断，冷却后仅允许一次半开探测。

所有 Key 不可用时，`web_fetch` 和 `web_map` 返回 `tavily_all_keys_unavailable` 及脱敏状态摘要。`web_search` 会保留已有 Grok 结果，但设置 `partial=true` 并返回 `tavily_error`，明确说明 Tavily 补充失败。该错误只终止当前工具调用，不会退出 MCP 进程。

## 常见问题

### 客户端找不到工具

确认 `uvx` 在客户端进程的 `PATH` 中，并检查仓库地址、命令名 `grok-search` 和 JSON/TOML 语法。Windows 客户端如果找不到 `uvx`，可填写其绝对路径。

### Grok 搜索可用，但抓取或映射失败

`web_fetch` 和 `web_map` 依赖 Tavily。调用 `get_config_info`，确认 Tavily 已启用并配置了 `TAVILY_API_KEY` 或 `TAVILY_API_KEYS`。

### 企业网络出现证书错误

在 `uvx` 参数开头加入 `--native-tls`，让 uv 使用系统证书库。完整示例见客户端配置指南。

### 是否会泄露 API Key

配置诊断只返回脱敏 Key。不要把真实 Key 写入仓库、Issue、日志截图或客户端共享配置。

## 本地开发

```bash
git clone https://github.com/Timmyzzo/WebSearch-MCP
cd WebSearch-MCP
uv sync --extra dev
uv run ruff check .
uv run pytest
uv run python -m build
```

更多模块说明、测试范围和阶段边界见 [开发者指南](./docs/DEVELOPMENT.md)。

## 许可证

[MIT License](LICENSE)
