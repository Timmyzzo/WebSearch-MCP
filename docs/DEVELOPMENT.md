# WebSearch MCP 开发者指南

需求与验收标准以 [DEVELOPMENT_ROADMAP.md](./DEVELOPMENT_ROADMAP.md) 为准。本文只说明当前代码结构、验证命令和阶段边界。

## 1. 模块结构

```text
src/grok_search/
├─ app.py                 FastMCP 实例
├─ server.py              stdio 入口
├─ lifecycle.py           信号处理与 Windows 父进程监控
├─ config.py              环境变量、模型配置和 Tavily Key 轮询
├─ models.py              公共结构化响应模型
├─ protocol.py            三态协议、错误对象构造与诊断脱敏
├─ prompts.py             Grok 搜索 Prompt
├─ sources.py             信源提取、合并与会话缓存
├─ clients/
│  ├─ grok.py             OpenAI 兼容 Grok 客户端与流式解析
│  └─ tavily.py           Tavily Search、Extract、Map 客户端
└─ tools/
   ├─ web.py              搜索、信源、抓取与映射工具
   ├─ configuration.py    配置诊断与模型切换工具
   └─ planning.py         可选的分阶段规划工具
```

`server.py` 应保持轻量。网络协议逻辑放在 `clients/`，MCP 参数和编排放在 `tools/`，跨工具返回结构放在 `models.py`。

## 2. 本地环境

```bash
uv sync --extra dev
```

运行检查：

```bash
uv run ruff check .
uv run pytest
uv run python -m build
```

测试覆盖：

- 配置解析和 Tavily Key 基础轮询。
- Grok OpenAI 兼容 SSE 与模型列表。
- Tavily Search、Extract、Map 模拟请求。
- MCP 工具参数、结构化输出和可选 Context。
- 标准 MCP stdio 初始化、工具发现和调用。
- `success`、`partial_success`、`error` 三态及通用错误对象 Schema。
- Grok/Tavily 组合、合法空结果、旧字段映射、脱敏和并发状态隔离。
- 动态搜索深度、时效上下文、来源等级、领域策略、Prompt 注入边界和确定性来源去重。
- stdio 同一进程内的成功、部分成功、错误、参数校验错误及错误后存活。

## 3. MCP 兼容约束

- stdout 只能用于 MCP stdio 协议，不输出 Banner 或调试文本。
- 工具参数必须能表达为简单、稳定的 JSON Schema。
- `Context` 是可选注入能力，不能成为客户端必填参数。
- 不修改 Cherry Studio、Claude Code 或 Codex 的本地配置。
- 正常结果与错误结果都返回结构化对象。
- 所有工具以 `status` 为权威状态，并保留 `error`、`partial`、`tavily_error`、`grok_error` 等兼容字段。
- 规范错误位于 `error_detail`，必须包含稳定 `code`、用户消息、`service` 和 `retryable`。
- Windows 父进程监控改动必须通过 stdio 子进程测试。

## 4. 当前阶段边界

P0、P1、P2、P3、P4 和 P5 已完成。P2 实现包括：

- 多 Key 正常轮询与共享健康状态。
- 错误分类和 `Retry-After` 解析。
- Key 级状态与熔断。
- Tavily 服务级熔断和半开探测。
- 连接池复用。
- 所有 Key 不可用时的稳定错误。

运行时由进程级共享 `TavilyClient` 持有，三个端点复用同一个 `httpx.AsyncClient`、Key 健康状态和服务熔断器。FastMCP lifespan 在正常关闭时调用 `aclose()` 释放连接池。

可靠性配置为 `TAVILY_KEY_COOLDOWN`、`TAVILY_QUOTA_COOLDOWN`、`TAVILY_SERVICE_FAILURE_THRESHOLD` 和 `TAVILY_SERVICE_COOLDOWN`。

P3 在不提前实现 P4 统一协议的前提下增加了：

- `GROK_PRIMARY_MODEL`、`GROK_FALLBACK_MODEL` 和每模型实际请求上限。
- `GROK_MODEL` 到主模型的兼容映射、空值处理和相同主备模型去重。
- Grok 进程级共享 `httpx.AsyncClient`、连接池与 FastMCP lifespan 关闭。
- 按 HTTP 状态和 OpenAI 兼容错误对象分类的重试、提前切换和直接失败。
- 流式响应完成性校验，以及不会缓存或返回残缺流的结构化最终错误。
- 主备模型独立尝试计数、随机抖动指数退避和 stdio 错误后存活测试。

P4 在保留 P2/P3 兼容字段和可靠性语义的前提下增加了：

- 全工具统一 `success`、`partial_success`、`error` 三态。
- 规范 `error_detail`：稳定错误码、用户消息、服务名、可重试性、HTTP/上游错误码和脱敏诊断。
- `web_search` 的 Grok/Tavily 四种组合语义；Tavily 不能伪装 Grok 答案。
- 空答案、空抓取内容和空 URL 映射与真实上游失败的独立错误码。
- `get_sources`、配置、模型切换和保留规划工具的稳定结构化响应。
- P2 `tavily_error`、P3 `grok_error`、旧 `error`/`partial`/`content`/`results` 字段的兼容映射。
- API Key、Authorization、可能回显凭据的响应正文、traceback 和内部对象表示的错误输出隔离。
- 固定 MCP 输出 Schema、可选 `Context`、并发响应隔离，以及错误后 stdio 进程存活测试。

P5 在不改变工具 Schema、P2/P3 可靠性和 P4 返回协议的前提下增加了：

- 纯函数式查询分类，按简单事实、单一官方文档、强时效、比较、高风险、复杂技术、小众和争议问题选择 `fast`、`standard` 或 `deep` 有界搜索策略。
- 运行时当前日期、时间、时区和 UTC 偏移上下文；强时效查询要求核对稳定/预览/历史/废弃版本、发布日期和资料更新时间。
- 通用来源等级、独立证据链和关键结论映射规则；确定性 URL 规范化只移除 fragment、常见追踪参数、默认端口和 `www` 差异，不提前实现复杂内容聚类。
- 软件/GitHub、健身健康营养、汽车安全和小众证据稀缺问题的领域策略，以及反证、限制、争议和不确定性表达。
- 固定系统规则与 JSON 搜索请求的信任边界；用户查询、平台字段和网页内容都作为不可信数据，不返回内部推理或敏感配置。
- 每次调用独立构造 Prompt 和搜索配置；规划工具保持可选，不是 `web_search` 前置步骤。

P5 没有执行 P6 的 Cherry Studio、Claude Code、Codex 真实人工验收，也没有实现复杂缓存、持久化答案、RAG、浏览器自动化或新的抓取降级服务。敏感日志整体重构、日志轮转和其他路线图暂缓事项仍未实现。

## 5. 提交前检查

```bash
uv run ruff check .
uv run pytest
uv run python -m build
git diff --check
```

同时确认：

- 新增环境变量已写入中英文 README。
- 工具 Schema 变更有自动化测试。
- 错误消息不包含完整 API Key。
- Cherry Studio、Claude Code 和 Codex 的 stdio 启动方式仍然一致。
- 没有实现路线文档明确标记为暂缓的事项。
