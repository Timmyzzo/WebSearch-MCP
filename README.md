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
- 下一阶段：P2 Tavily 多 Key 错误分类、Key 级熔断和服务级熔断。

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
| `GROK_MODEL` | 否 | `grok-4-fast` | 默认 Grok 模型。 |
| `TAVILY_API_KEY` | 否 | - | 单个 Tavily Key。 |
| `TAVILY_API_KEYS` | 否 | - | 多个 Tavily Key，支持逗号、分号或换行分隔，优先于单 Key。 |
| `TAVILY_API_URL` | 否 | `https://api.tavily.com` | Tavily API 根地址。 |
| `TAVILY_ENABLED` | 否 | `true` | 是否启用 Tavily。 |
| `GROK_DEBUG` | 否 | `false` | 是否记录调试信息。 |
| `GROK_LOG_LEVEL` | 否 | `INFO` | 日志级别。 |
| `GROK_LOG_DIR` | 否 | `logs` | 日志目录。 |
| `GROK_RETRY_MAX_ATTEMPTS` | 否 | `3` | Grok 重试配置。 |
| `GROK_RETRY_MULTIPLIER` | 否 | `1` | 指数退避乘数。 |
| `GROK_RETRY_MAX_WAIT` | 否 | `10` | 单次退避最大秒数。 |

只配置 Grok 时，`web_search` 仍可使用。设置 `TAVILY_ENABLED=false` 会禁用 Tavily，即使环境中存在 Tavily Key。

## 工具概览

| 工具 | 用途 | 主要返回字段 |
| --- | --- | --- |
| `web_search` | Grok 主搜索，可选 Tavily 补充信源 | `session_id`、`content`、`sources_count`、`error` |
| `get_sources` | 读取某次搜索的完整信源 | `session_id`、`sources`、`sources_count`、`error` |
| `web_fetch` | 使用 Tavily Extract 提取 Markdown | `url`、`content`、`provider`、`error` |
| `web_map` | 使用 Tavily Map 发现站点结构 | `base_url`、`results`、`response_time`、`error` |
| `get_config_info` | 查看脱敏配置并测试 Grok 连接 | `configuration`、`connection_test` |
| `switch_model` | 持久化默认 Grok 模型 | `success`、`previous_model`、`current_model` |

`web_search` 的 `query` 是唯一必填参数。规划工具是可选能力，不是搜索前置步骤；所有 `thought` 参数均为可选。

## 多 Tavily Key

可以使用逗号、分号或换行配置多个 Key：

```text
TAVILY_API_KEYS=tvly-key-1,tvly-key-2,tvly-key-3
```

当前版本会轮询选择 Key。Key 健康状态、错误分类和熔断属于下一阶段 P2，不应把当前轮询误认为完整的故障转移机制。

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
