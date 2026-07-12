![WebSearch MCP](./images/title.png)

<div align="center">

[English](./docs/README_EN.md) | 简体中文

面向 Cherry Studio、Claude Code 和 Codex 的标准 MCP 网络搜索服务

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![MCP stdio](https://img.shields.io/badge/MCP-stdio-green.svg)](https://modelcontextprotocol.io/)

</div>

## 项目简介

WebSearch MCP 使用 Grok 完成 AI 驱动的联网搜索，并使用 Tavily 提供结构化搜索结果、网页正文提取和站点映射。服务基于标准 MCP stdio transport，不依赖任何单一客户端的私有配置。

```text
MCP Client ──stdio──► WebSearch MCP
                       ├─ web_search ─► Grok + 可选 Tavily 信源
                       ├─ web_fetch  ─► Tavily Extract
                       └─ web_map    ─► Tavily Map
```

主要能力：

- Grok OpenAI 兼容接口搜索，支持按请求指定模型。
- Tavily Search、Extract、Map。
- 多个 Tavily Key 的逗号、分号或换行配置与轮询。
- 搜索信源缓存与 `get_sources` 二次读取。
- 简单、稳定的 JSON Schema 和结构化工具结果。
- Windows 父进程监控，兼容长时间运行的 stdio 客户端。

## 安装

需要 Python 3.10+ 和 [uv](https://docs.astral.sh/uv/getting-started/installation/)。所有安装示例均从以下仓库启动：

```text
https://github.com/Timmyzzo/WebSearch-MCP
```

### Cherry Studio

在 Cherry Studio 的 MCP 服务器设置中添加：

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

如果所在网络需要使用系统证书库，可在 `args` 的开头加入 `"--native-tls"`。

### Codex

在 `~/.codex/config.toml` 中添加：

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

## 环境变量

| 变量 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `GROK_API_URL` | 是 | - | OpenAI 兼容 API 根地址，需提供 `/chat/completions` 和 `/models`。 |
| `GROK_API_KEY` | 是 | - | Grok API Key。 |
| `GROK_MODEL` | 否 | `grok-4-fast` | 默认 Grok 模型。 |
| `TAVILY_API_KEY` | 否 | - | 单个 Tavily Key。 |
| `TAVILY_API_KEYS` | 否 | - | 多个 Tavily Key，支持逗号、分号和换行分隔；优先于单 Key。 |
| `TAVILY_API_URL` | 否 | `https://api.tavily.com` | Tavily API 根地址。 |
| `TAVILY_ENABLED` | 否 | `true` | 是否启用 Tavily。 |
| `GROK_DEBUG` | 否 | `false` | 是否记录调试信息。 |
| `GROK_LOG_LEVEL` | 否 | `INFO` | 日志级别。 |
| `GROK_LOG_DIR` | 否 | `logs` | 日志目录。 |
| `GROK_RETRY_MAX_ATTEMPTS` | 否 | `3` | Grok 重试配置。 |
| `GROK_RETRY_MULTIPLIER` | 否 | `1` | 指数退避乘数。 |
| `GROK_RETRY_MAX_WAIT` | 否 | `10` | 单次退避最大秒数。 |

只配置 Grok 时，`web_search` 可正常使用；`web_fetch`、`web_map` 和额外 Tavily 信源需要 Tavily Key。

## MCP 工具

核心工具：

- `web_search(query, platform="", model="", extra_sources=0)`：返回 `session_id`、回答正文和信源数量。
- `get_sources(session_id)`：读取某次搜索缓存的完整信源。
- `web_fetch(url)`：通过 Tavily Extract 返回 Markdown 内容。
- `web_map(url, instructions="", max_depth=1, max_breadth=20, limit=50, timeout=150)`：发现站点 URL 结构。
- `get_config_info()`：返回脱敏配置并测试 Grok 连接。
- `switch_model(model)`：持久化默认 Grok 模型。

另提供可选的分阶段规划工具。规划不是 `web_search` 的前置条件，所有 `thought` 参数均为可选。

服务不会修改 Claude Code、Codex 或 Cherry Studio 的本地配置。若要调整客户端自带网络工具，请在对应客户端中手动配置。

## 本地开发

```bash
git clone https://github.com/Timmyzzo/WebSearch-MCP
cd WebSearch-MCP
uv sync --extra dev
uv run ruff check .
uv run pytest
```

也可以直接启动 stdio 服务：

```bash
uv run grok-search
```

## 许可证

[MIT License](LICENSE)
