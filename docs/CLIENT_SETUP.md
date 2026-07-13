# WebSearch MCP 客户端配置指南

本文提供 Cherry Studio、Claude Code 和 Codex 的标准 MCP stdio 配置。所有示例都从以下仓库启动：

```text
https://github.com/Timmyzzo/WebSearch-MCP
```

## 1. 公共要求

安装 [uv](https://docs.astral.sh/uv/getting-started/installation/)，并确保客户端进程能找到 `uvx`：

```bash
uvx --version
```

最小环境变量：

```text
GROK_API_URL=https://your-api-endpoint.example/v1
GROK_API_KEY=your-grok-api-key
GROK_PRIMARY_MODEL=grok-4-fast
GROK_MODEL_MAX_ATTEMPTS=5
GROK_MAX_CONCURRENCY=2
WEB_SEARCH_TOTAL_TIMEOUT=270
```

如需网页提取、站点映射或额外信源，再配置：

```text
TAVILY_API_KEY=tvly-your-tavily-key
```

多个 Tavily Key 使用 `TAVILY_API_KEYS`，例如 `key-1,key-2,key-3`。

`GROK_PRIMARY_MODEL` 未设置或为空时，会使用兼容变量 `GROK_MODEL`，再回退到持久化配置和 `grok-4-fast`。服务只使用这个模型，不自动降级到备用模型；可恢复故障默认最多真实调用 5 次。

可选可靠性参数：`TAVILY_PER_KEY_MAX_CONCURRENCY=1`、`TAVILY_KEY_COOLDOWN=30`、`TAVILY_QUOTA_COOLDOWN=3600`、`TAVILY_SERVICE_FAILURE_THRESHOLD=2`、`TAVILY_SERVICE_COOLDOWN=30`。`GROK_MAX_CONCURRENCY` 的安全上限为 2，Tavily 每 Key 并发当前必须为 1，通常保持默认值即可。

## 2. Cherry Studio

在 MCP 服务器设置中新增一个 stdio 服务：

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

保存并重启服务后，确认工具列表中存在 `web_search`、`web_fetch` 和 `web_map`。

在 Cherry Studio 的 MCP 服务器高级设置中，把工具调用超时设置为 **300 秒**。300 秒只是客户端安全上限，不是搜索性能目标；服务端默认会在约 270 秒内主动返回业务结果或结构化超时，避免客户端先产生裸 `-32001`。

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

PowerShell 中使用 here-string 可避免 JSON 引号转义问题：

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

验证：

```bash
claude mcp list
```

## 4. Codex

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

重启 Codex 会话后，确认 MCP 服务已连接并能列出核心工具。

## 5. 企业网络与代理

遇到自签名证书或企业证书链错误时，在 `--from` 前加入 `--native-tls`：

```json
"args": [
  "--native-tls",
  "--from",
  "git+https://github.com/Timmyzzo/WebSearch-MCP",
  "grok-search"
]
```

代理环境可通过客户端的 MCP `env` 传入 `HTTP_PROXY`、`HTTPS_PROXY` 和 `NO_PROXY`。

## 6. 验收步骤

建议按顺序执行：

1. 调用 `get_config_info`，确认 Key 已脱敏；连接正常时 `status` 为 `success`，仅连接测试失败时为 `partial_success` 并提供 `error_detail`。
2. 调用 `web_search` 搜索一个近期主题，确认完整结果为 `status="success"`。
3. 使用返回的 `session_id` 调用 `get_sources`；有效会话即使没有来源也应返回 `success` 和空 `sources`。
4. 调用 `web_fetch` 提取一个公开网页。上游成功但确实没有正文时返回 `error`/`tavily_no_content`，不同于配置或服务故障。
5. 调用 `web_map` 映射一个小型文档站点，先保持 `max_depth=1`。没有 URL 时返回 `error`/`tavily_no_urls`。
6. 制造一次可恢复错误后再次列出或调用工具，确认 MCP 进程仍然存活。
7. 并发发起两个 `web_search`，再发起第三个，确认第三个排队且前三个都在 300 秒内返回业务层结果或结构化错误。
8. 检查 `grok_error` 中的 `termination_reason`、`configured_max_attempts`、`actual_attempts`、`elapsed_ms`、`budget_ms` 和 `queue_wait_ms` 与实际行为一致。

所有工具的规范错误对象都位于 `error_detail`，至少包含 `code`、`message`、`service` 和 `retryable`；存在时还包含 `http_status`、`upstream_code` 与脱敏 `diagnostics`。旧字段 `error`、`partial`、`tavily_error`、`grok_error` 仍保留兼容。

超时层级应保持：客户端工具外层 300 秒 > `web_search` 服务端总预算 270 秒 > Grok 单次读取上限 120 秒。最大尝试次数、并发排队、HTTP/流读取、退避和 `Retry-After` 共用 270 秒总预算，因此“最多 5 次”不代表一定执行满 5 次。默认同一进程最多 2 个 Grok 请求；Tavily Search、Extract、Map 每个 Key 合计最多 1 个真实请求，不同健康 Key 可以并发。

P5 不增加客户端参数或返回字段。所有 `web_search` 至少覆盖 5 个独立视角并深挖 2 个方向，普通问题通常形成 7–12 次检索动作，人物、强时效、高风险、比较、小众和争议问题通常为 10–16 次。查询会使用原生语言和相关实体语言扩展；“最新/当前”等请求使用运行时实际日期与时区。设置 `extra_sources>0` 后，Tavily 候选证据会进入 Grok 的最终综合。

## 7. 常见故障

| 现象 | 检查项 |
| --- | --- |
| 服务无法启动 | `uvx` 是否在客户端 PATH；仓库地址和命令名是否正确。 |
| 启动超时 | 首次安装可能需要下载依赖；提高 `startup_timeout_sec`。 |
| JSON 配置报错 | 检查尾逗号、引号和 PowerShell 转义；优先使用 here-string。 |
| Grok 连接失败 | 检查 `GROK_API_URL` 是否包含正确的 API 根路径及 `/models` 支持。 |
| Grok 模型最终失败 | 先查看 `error_detail`，再查看兼容的 `grok_error` 尝试次数和最后错误分类；认证、参数、模型不存在和无权限错误会立即停止。 |
| Cherry Studio 显示 `-32001` | 将 MCP 工具超时设为 300 秒；确认 `WEB_SEARCH_TOTAL_TIMEOUT` 保持 270 秒或更低。 |
| 抓取或映射报配置错误 | 配置 Tavily Key，并确认 `TAVILY_ENABLED` 未设为 `false`。 |
| 客户端显示部分成功 | 检查 `status="partial_success"`、`error_detail` 和组件兼容字段；可用结果仍可使用。 |
| 证书验证失败 | 为 `uvx` 增加 `--native-tls`，或检查企业代理证书。 |

不要把真实 API Key 提交到仓库或粘贴到公开 Issue。
