![WebSearch MCP](./images/title.png)

<div align="center">

[English](./docs/README_EN.md) | 简体中文

面向 Cherry Studio、Claude Code 与 Codex 的标准 MCP 网络搜索服务

**深度检索 · 单强模型五次重试 · Tavily 多 Key 熔断 · 稳定三态协议**

[![CI](https://github.com/Timmyzzo/WebSearch-MCP/actions/workflows/ci.yml/badge.svg)](https://github.com/Timmyzzo/WebSearch-MCP/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![MCP stdio](https://img.shields.io/badge/MCP-stdio-green.svg)](https://modelcontextprotocol.io/)

</div>

<p align="center">
  <a href="#快速开始">快速开始</a> ·
  <a href="#为什么选择-websearch-mcp">核心能力</a> ·
  <a href="#工具概览">工具</a> ·
  <a href="#配置">配置</a> ·
  <a href="./docs/CLIENT_SETUP.md">客户端接入</a>
</p>

## WebSearch MCP 是什么

WebSearch MCP 把 Grok 的 AI 联网搜索与 Tavily 的结构化检索、网页提取和站点映射组合成一个标准 MCP stdio 服务。它不依赖某个客户端的私有能力，也不会修改 Cherry Studio、Claude Code 或 Codex 的本地配置。

```text
MCP Client ──stdio──► WebSearch MCP
                       ├─ web_search ─► Grok + 可选 Tavily 信源
                       ├─ get_sources ─► 搜索信源缓存
                       ├─ web_fetch  ─► Tavily Extract
                       └─ web_map    ─► Tavily Map
```

## 为什么选择 WebSearch MCP

| 能力 | 实际行为 |
| --- | --- |
| 深度优先 | 每次搜索都执行有界深度研究，通常进行 4–8 个多角度检索，不再因查询短而走快速路径。 |
| 强模型优先 | 始终使用用户配置的单一最强 Grok 模型；临时错误默认最多真实调用 5 次。 |
| 证据融合 | Tavily 候选证据会进入 Grok 的同一次核验与最终综合，而不是只在事后缓存。 |
| 可解释可靠性 | Tavily 多 Key、Key/服务级熔断、`Retry-After`、Grok 流完整性校验。 |
| 稳定兼容 | 标准 MCP stdio、固定工具 Schema、统一 `success` / `partial_success` / `error`。 |

适合以下场景：

- 让编码助手检索最新官方文档、Release、Issue 和技术资料。
- 获取带可追溯信源的实时搜索答案。
- 把网页正文提取为 Markdown，或发现文档站点的 URL 结构。
- 在多个 MCP 客户端之间复用相同工具 Schema 和环境变量。

## 当前状态

- P0 仓库与测试基线：已完成。
- P1 旧抓取服务清理与模块化：已完成。
- P2 Tavily 多 Key 可靠性：已完成。
- P3 Grok 单强模型与重试：已完成。
- P4 统一返回协议：已完成。
- P5 搜索 Prompt 与搜索质量重构：已完成。
- 下一阶段：P6 跨客户端真实人工验收。

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
    "GROK_MODEL_MAX_ATTEMPTS": "5",
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
| `GROK_PRIMARY_MODEL` | 否 | 见下文 | 每次搜索使用的强模型名称，由用户自行填写。 |
| `GROK_MODEL_MAX_ATTEMPTS` | 否 | `5` | 当前模型对可恢复故障的最多真实请求次数，必须为正整数。 |
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

模型解析优先级为：当前进程中 `switch_model` 设置的模型、非空 `GROK_PRIMARY_MODEL`、非空 `GROK_MODEL`、配置文件中的模型、默认值 `grok-4-fast`。环境变量仅包含空白时视为未设置。服务不会自动降级到较弱备用模型；请直接配置你希望使用的最强可用模型。

## 工具概览

| 工具 | 用途 | 工具专属字段 |
| --- | --- | --- |
| `web_search` | Grok 主搜索，可选 Tavily 候选证据综合 | `session_id`、`content`、`sources_count`、`grok_error`、`tavily_error` |
| `get_sources` | 读取某次搜索的完整信源 | `session_id`、`sources`、`sources_count` |
| `web_fetch` | 使用 Tavily Extract 提取 Markdown | `url`、`content`、`provider`、`tavily_error` |
| `web_map` | 使用 Tavily Map 发现站点结构 | `base_url`、`results`、`response_time`、`tavily_error` |
| `get_config_info` | 查看脱敏配置并测试 Grok 连接 | `configuration`、`connection_test` |
| `switch_model` | 持久化并切换当前进程的 Grok 主模型 | `success`、`previous_model`、`current_model` |

所有工具还统一返回 `status`、`error`、`error_detail` 和 `partial`。`web_search` 的 `query` 是唯一必填参数。规划工具是可选能力，不是搜索前置步骤；所有 `thought` 参数均为可选。

## 搜索质量与深度优先策略

每次 `web_search` 都使用有界 `deep` 策略，通常进行 4–8 个多角度检索，并在关键结论收敛后停止。简单事实和单一官方文档也不会降级为快速路径，但答案篇幅仍会按问题本身保持简洁。

这些数量是 Prompt 中的有界搜索预算，不会形成无限工具循环。模糊实体调查会扩展别名、账号、组织、团队、协作者、事件与时间范围，并把结论分为直接确认、强支持、合理候选和冲突/排除，同时给出可解释的置信度。缺少单一实名绑定页不会让搜索提前停止，但不会把推测伪装成事实。用户查询与平台提示以 JSON 数据传递；网页、搜索片段和用户输入中的指令不能覆盖系统搜索规则。

当 `extra_sources>0` 时，Tavily 会先提供结构化 URL、标题和摘要候选，Grok 再结合自身联网搜索完成证据核对与答案综合；候选内容仍被视为不可信资料，不会覆盖系统规则。Tavily 失败时 Grok 仍可返回 `partial_success`，Grok 失败时 Tavily 仍不能替代最终答案。

通用来源优先级为：官方文档/标准/法规/原始数据/论文与系统综述，权威机构和项目维护团队，有事实核查的专业媒体，专业实践经验，最后才是博客、论坛和社交媒体线索。关键结论优先使用高等级来源；转载同一原始消息不算独立证据，证据不足时会明确说明。

领域策略包括：

- 软件与 GitHub：优先当前默认分支文档、README、Release、Changelog、迁移指南、API Reference、commit、issue、PR 和维护者说明，并核对稳定版、发布日期、弃用与最终合并代码。
- 健身、健康、营养与恢复：区分研究支持、专家实践和运动员个人经验，结合训练年龄、伤病、基础、恢复、设备和周期；伤病、疾病、药物或极端饮食明确医疗评估边界。
- 汽车和其他高风险安全问题：优先官方测试与真实事故数据，区分碰撞避免和乘员保护，不跨不兼容标准机械比较星级，并说明统计限制和不确定性。
- 小众、模糊或证据稀缺问题：先定义概念，必要时使用同义词或多语言检索，主动寻找反例、失败案例和不同学派，并尝试用两类独立来源交叉验证。

“最新、当前、今天、现版本、仍然支持”等查询会使用运行时实际日期和时区，核对版本、发布日期和资料更新时间。复杂答案按需要说明证据等级、争议、限制、适用范围和不确定性；简单答案不会被强制套用冗长模板。P4 的 `success`、`partial_success`、`error`、`error_detail` 和全部兼容字段保持不变。

## 统一返回协议

`status` 只有三种稳定值：

- `success`：工具目标完整完成。合法的空信源列表可以成功，例如 Grok 给出有效答案但没有来源。
- `partial_success`：已返回可用结果，但某个补充组件或非关键步骤失败。例如 Grok 成功、Tavily 补充失败；规划尚未完成；站点映射包含部分无效项。
- `error`：当前工具目标未完成。空答案、空抓取内容、空 URL 映射、配置错误和上游失败都不会伪装成成功。

| 工具 | `success` | `partial_success` | `error` 与空结果 |
| --- | --- | --- | --- |
| `web_search` | Grok 返回非空有效答案；来源可以为空。 | Grok 成功但已请求的 Tavily 补充失败。 | Grok 最终失败、流中断、无效/空答案或配置错误；Tavily 成功不能替代 Grok 答案。 |
| `get_sources` | 会话存在；`sources=[]` 是合法空结果。 | 缓存中只有部分来源可验证。 | 会话不存在/过期或缓存组件失败。 |
| `web_fetch` | Tavily 返回非空 Markdown。 | 当前单 URL 提取是原子操作，暂无部分成功。 | 配置、认证、限流、服务、参数错误，或上游成功但无正文的 `tavily_no_content`。 |
| `web_map` | 返回至少一个 URL 且响应完整。 | 返回了 URL，但缺少根 URL 或忽略了无效项。 | Tavily 故障，或上游成功但没有 URL 的 `tavily_no_urls`。 |
| `get_config_info` | 脱敏配置读取和 Grok 连接测试均成功。 | 配置可返回，但连接/认证/配置测试失败。 | 连脱敏配置对象都无法构造。 |
| `switch_model` | 主模型成功写入当前进程和兼容配置。 | 原子写入，暂无部分成功。 | 模型为空或配置持久化失败；仍只修改主模型。 |
| 规划工具 | 所需阶段已完成并生成可执行计划。 | 会话有效但仍有必需阶段未完成。 | 会话不存在、JSON 参数无效或规划组件失败。 |

规范错误位于 `error_detail`：

```json
{
  "code": "tavily_service_unavailable",
  "message": "Tavily 服务暂时不可用",
  "service": "tavily",
  "retryable": true,
  "http_status": 503,
  "upstream_code": "upstream_unavailable",
  "diagnostics": {
    "service_circuit": {"state": "open", "retry_after_seconds": 30}
  }
}
```

诊断信息只包含必要的脱敏字段，不包含 Grok/Tavily Key、Authorization 头、可能回显凭据的响应正文、Python traceback 或内部对象表示。结构化错误只结束当前工具调用，stdio MCP 进程仍可发现工具并执行后续调用。

兼容字段映射：

| 旧字段 | P4 映射 |
| --- | --- |
| `error` | 继续保留字符串形式的旧错误码或旧消息；新调用方应读取 `error_detail`。 |
| `partial` | `status="partial_success"` 时为 `true`，其他状态默认为 `false`。 |
| `tavily_error` | 保留 P2 Key 状态与服务熔断摘要，并补充重试性、HTTP/上游错误码。 |
| `grok_error` | 保留 P3 兼容字段；单模型模式下 `fallback_model=null`、`fallback_attempts=0`、`switched_model=false`。 |
| `content`、`results`、`success` | 继续保留原工具字段；是否成功统一以 `status` 为准。 |

典型返回如下。

`web_search` 完整成功；有效答案没有来源仍是成功：

```json
{"status":"success","session_id":"abc123","content":"有效答案","sources_count":0,"error":null,"error_detail":null,"partial":false}
```

Grok 成功但 Tavily 补充失败：

```json
{"status":"partial_success","session_id":"abc123","content":"有效答案","sources_count":0,"partial":true,"error":null,"error_detail":{"code":"tavily_all_keys_unavailable","message":"所有 Tavily Key 均不可用","service":"tavily","retryable":false,"http_status":401,"upstream_code":"invalid_api_key","diagnostics":{"key_statuses":[{"fingerprint":"tvly…1234","state":"invalid"}]}},"tavily_error":{"code":"tavily_all_keys_unavailable","message":"所有 Tavily Key 均不可用"}}
```

Grok 最终失败时，即使 Tavily 成功也不会伪装为答案：

```json
{"status":"error","session_id":"abc123","content":"","sources_count":0,"error":"grok_primary_failed","error_detail":{"code":"grok_primary_failed","message":"Grok 模型调用失败，已用尽当前模型的重试次数","service":"grok","retryable":true,"http_status":503,"upstream_code":"upstream_unavailable","diagnostics":{"primary_attempts":5,"fallback_attempts":0,"total_attempts":5,"switched_model":false}},"partial":false}
```

其他工具示例：

```jsonl
{"tool":"get_sources","status":"success","session_id":"abc123","sources":[],"sources_count":0}
{"tool":"web_fetch","status":"success","url":"https://example.com","content":"# Page","provider":"tavily"}
{"tool":"web_map","status":"error","base_url":"https://example.com","results":[],"error_detail":{"code":"tavily_no_urls","message":"Tavily 请求成功，但没有发现可返回的 URL","service":"tavily","retryable":false,"http_status":null,"upstream_code":null,"diagnostics":{"upstream_succeeded":true,"empty_result":true}}}
{"tool":"get_config_info","status":"partial_success","partial":true,"configuration":{"GROK_API_KEY":"未配置"},"connection_test":{"status":"配置错误"},"error_detail":{"code":"grok_configuration_error","message":"GROK_API_KEY 未配置","service":"grok","retryable":false,"http_status":null,"upstream_code":null,"diagnostics":{"configuration":"grok"}}}
{"tool":"switch_model","status":"success","success":true,"previous_model":"grok-4-fast","current_model":"grok-3-mini","message":"主模型已切换"}
{"tool":"plan_intent","status":"partial_success","partial":true,"session_id":"plan123","plan_complete":false,"phases_remaining":["complexity_assessment","query_decomposition"],"error_detail":{"code":"planning_incomplete","message":"搜索计划尚未完成，可继续提交剩余规划阶段","service":"planning","retryable":true,"http_status":null,"upstream_code":null,"diagnostics":{"phases_remaining":["complexity_assessment","query_decomposition"]}}}
```

## Grok 单强模型与五次重试

每次调用只使用用户配置的当前模型。408、429、5xx、连接失败、连接/读取超时、完整内容产生前或流式传输中的中断，以及可识别的中转站“上游账号不可用/死号/账号池不可用”错误，会按带随机抖动的指数退避重试，默认最多执行 5 次真实请求。

模型不存在或无权限会立即停止；模型暂时不可用会继续重试当前模型。明确的 400/422 参数错误和 401/403/API Key 认证失败也会立即停止。错误分类同时检查 HTTP 状态、OpenAI 兼容错误对象、错误码、错误类型和正文语义。

流内容会在服务端完整缓冲并校验结束标志。流在产生部分内容后中断时，残缺内容不会作为成功答案返回、缓存或提取来源。最终失败返回 `grok_error`，包含当前模型、真实尝试次数、最后错误分类、状态码/上游错误码，并保留值为 `null`/`0`/`false` 的旧备用模型兼容字段；不会包含 API Key 或 Authorization 值。

`switch_model(model)` 保持旧调用形式不变：它更新当前进程使用的模型，并将 `primary_model`（同时保留兼容的 `model` 字段）写入本地配置。

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

所有 Key 不可用时，`web_fetch` 和 `web_map` 返回 `status="error"`、`tavily_all_keys_unavailable` 及脱敏状态摘要。`web_search` 会保留已有 Grok 结果，返回 `status="partial_success"`，同时设置 `partial=true` 并保留 `tavily_error`。该错误只终止当前工具调用，不会退出 MCP 进程。

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
