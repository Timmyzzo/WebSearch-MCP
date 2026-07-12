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
```

如需网页提取、站点映射或额外信源，再配置：

```text
TAVILY_API_KEY=tvly-your-tavily-key
```

多个 Tavily Key 使用 `TAVILY_API_KEYS`，例如 `key-1,key-2,key-3`。

可选可靠性参数：`TAVILY_KEY_COOLDOWN=30`、`TAVILY_QUOTA_COOLDOWN=3600`、`TAVILY_SERVICE_FAILURE_THRESHOLD=2`、`TAVILY_SERVICE_COOLDOWN=30`。通常保持默认值即可。

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
        "TAVILY_API_KEYS": "tvly-key-1,tvly-key-2"
      }
    }
  }
}
```

保存并重启服务后，确认工具列表中存在 `web_search`、`web_fetch` 和 `web_map`。

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
tool_timeout_sec = 180

[mcp_servers.grok-search.env]
GROK_API_URL = "https://your-api-endpoint.example/v1"
GROK_API_KEY = "your-grok-api-key"
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

1. 调用 `get_config_info`，确认 Key 已脱敏且 Grok `/models` 可访问。
2. 调用 `web_search` 搜索一个近期主题。
3. 使用返回的 `session_id` 调用 `get_sources`。
4. 调用 `web_fetch` 提取一个公开网页。
5. 调用 `web_map` 映射一个小型文档站点，先保持 `max_depth=1`。

## 7. 常见故障

| 现象 | 检查项 |
| --- | --- |
| 服务无法启动 | `uvx` 是否在客户端 PATH；仓库地址和命令名是否正确。 |
| 启动超时 | 首次安装可能需要下载依赖；提高 `startup_timeout_sec`。 |
| JSON 配置报错 | 检查尾逗号、引号和 PowerShell 转义；优先使用 here-string。 |
| Grok 连接失败 | 检查 `GROK_API_URL` 是否包含正确的 API 根路径及 `/models` 支持。 |
| 抓取或映射报配置错误 | 配置 Tavily Key，并确认 `TAVILY_ENABLED` 未设为 `false`。 |
| 证书验证失败 | 为 `uvx` 增加 `--native-tls`，或检查企业代理证书。 |

不要把真实 API Key 提交到仓库或粘贴到公开 Issue。
