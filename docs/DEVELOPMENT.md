# WebSearch MCP 开发者指南

需求与验收标准以 [DEVELOPMENT_ROADMAP.md](./DEVELOPMENT_ROADMAP.md) 为准。本文只说明当前代码结构、验证命令和阶段边界。

## 1. 模块结构

```text
src/grok_search/
├─ app.py                 FastMCP 实例
├─ server.py              stdio 入口
├─ lifecycle.py           信号处理与 Windows 父进程监控
├─ config.py              环境变量、模型配置和 Tavily Key 轮询
├─ budget.py              单次工具调用的单调时钟总预算与排队计时
├─ concurrency.py         可取消的异步并发槽位治理
├─ models.py              公共结构化响应模型
├─ protocol.py            三态协议、错误对象构造与诊断脱敏
├─ prompts.py             Grok 搜索 Prompt
├─ sources.py             信源提取、合并与会话缓存
├─ clients/
│  ├─ grok.py             Grok Chat/Responses 客户端、引用解析与完整性校验
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
- 深度搜索执行下限、增强预算、时效上下文、来源等级、领域策略、Prompt 注入边界和确定性来源去重。
- stdio 同一进程内的成功、部分成功、错误、参数校验错误及错误后存活。
- Grok 进程级最大并发 2、Tavily 每 Key 最大并发 1、不同 Key 并行、排队计入预算、重试受限和取消/异常释放。
- `web_search` 总预算耗尽、正确终止文案/诊断、超时后 stdio 存活及并发来源/会话隔离。
- Responses 显式 `web_search` 请求、citations/annotations/search trace、残缺响应重试、超时、取消、并发隔离和 stdio 错误后存活。
- 来源会话 TTL/LRU 与模型目录 TTL 刷新。

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

Tavily 调度还维护与健康状态分离的 Key 占用计数。Search、Extract、Map 获取同一种 Key 租约；忙碌不改变 `healthy` / `cooldown` / `quota_exhausted` / `invalid`，多个健康 Key 可并行，同一 Key 默认且当前强制最多一个真实请求。租约在成功、失败、取消、总预算超时和熔断切换路径中释放。

可靠性配置为 `TAVILY_KEY_COOLDOWN`、`TAVILY_QUOTA_COOLDOWN`、`TAVILY_SERVICE_FAILURE_THRESHOLD` 和 `TAVILY_SERVICE_COOLDOWN`。

P3 在不提前实现 P4 统一协议的前提下增加了：

- `GROK_PRIMARY_MODEL` 和当前模型实际请求上限；默认上限为 5。
- `GROK_MODEL` 到当前模型的兼容映射与空值处理；旧 fallback 配置不参与调度。
- Grok 进程级共享 `httpx.AsyncClient`、连接池与 FastMCP lifespan 关闭。
- 按 HTTP 状态和 OpenAI 兼容错误对象分类的重试、提前切换和直接失败。
- 流式响应完成性校验，以及不会缓存或返回残缺流的结构化最终错误。
- 单模型真实尝试计数、随机抖动指数退避和 stdio 错误后存活测试。

搜索超时与并发治理在 P2/P3/P4 兼容语义上增加：

- `WEB_SEARCH_TOTAL_TIMEOUT=270` 的调用级单调时钟预算，覆盖 Tavily 补充、Grok 槽位、真实请求、完整流读取、退避和 `Retry-After`。
- `GROK_MAX_CONCURRENCY=2` 的进程级共享异步限制器；每个真实重试重新获取槽位，120 秒单次读取上限会裁剪到剩余总预算。
- `TAVILY_PER_KEY_MAX_CONCURRENCY=1` 的共享 Key 租约；健康 Key 忙碌时优先调度其他 Key，全部忙碌时在调用预算内等待。
- `max_attempts_exhausted`、`non_retryable_error`、`total_budget_exhausted`、`concurrency_queue_timeout` 四类终止诊断，以及配置/实际尝试数、耗时、预算和排队毫秒数。
- 总预算错误只结束当前调用；Grok 失败而 Tavily 成功仍是 `error`，残缺流仍不得返回、缓存或用于来源提取。

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

- 纯函数式查询分类保留领域、时效和风险标签，但所有请求统一使用有界 `deep`；人物/组织、履历、奖项和公开记录会触发别名扩展与置信度分层。
- 搜索执行下限为 5 个独立广度视角加 2 个深挖方向；普通问题通常 7–12 次检索动作，增强研究通常 10–16 次，不以轻微改写冒充不同视角。
- 全局资料优先英文高质量来源，同时强制覆盖查询原生语言与相关实体、机构、赛事或本地记录所使用的语言。
- 运行时当前日期、时间、时区和 UTC 偏移上下文；强时效查询要求核对稳定/预览/历史/废弃版本、发布日期和资料更新时间。
- 通用来源等级、独立证据链和关键结论映射规则；确定性 URL 规范化只移除 fragment、常见追踪参数、默认端口和 `www` 差异，不提前实现复杂内容聚类。
- 软件/GitHub、健身健康营养、汽车安全和小众证据稀缺问题的领域策略，以及反证、限制、争议和不确定性表达。
- 固定系统规则与 JSON 搜索请求的信任边界；用户查询、平台字段和网页内容都作为不可信数据，不返回内部推理或敏感配置。
- 每次调用独立构造 Prompt 和搜索配置；规划工具保持可选，不是 `web_search` 前置步骤。
- 请求 `extra_sources` 时，先获取有界、截断且不可信的 Tavily 候选证据，再交给同一次 Grok 搜索做核对和最终综合；Tavily 失败及 Grok 失败仍保持 P4 组合语义。

外部项目代码审计后的兼容增强包括：

- `GROK_API_PROTOCOL=chat_completions|responses`；Chat 保持默认，Responses 是显式启用的可审计路径，不自动切换协议。
- Responses 请求使用 `/responses`、服务端 `web_search`、`parallel_tool_calls=true`、`store=false` 和 7–32 的有界 `max_tool_calls`。
- 仅 `status=completed` 且答案非空时成功；`incomplete`、`in_progress`、空内容和无效 JSON 复用 P3 重试、总预算、并发槽位和错误分类。
- citations、inline annotations、search result 与 open-page URL 被规范化并加入来源会话；Tavily 仍先进入 Grok 最终综合，不能替代失败答案。
- 来源会话为最大 256 项、1 小时 TTL 的进程内 LRU；模型目录成功结果缓存 5 分钟，失败不缓存。
- 设计来源、许可证边界与拒绝项记录在 [EXTERNAL_PROJECT_ANALYSIS.md](./EXTERNAL_PROJECT_ANALYSIS.md)。

P6 已完成 Cherry Studio 的工具发现、搜索、来源读取、抓取、映射、结构化错误和错误后存活人工测试；首次搜索曾出现一次客户端超时，上层模型也曾未自动转交 `session_id`，但重试及手动传值后服务端链路正常。Claude Code 和 Codex 的真实人工验收仍未完成。P5/P6 没有实现复杂缓存、持久化答案、RAG、浏览器自动化或新的抓取降级服务。

当前已完成针对 Cherry Studio `-32001` 根因的服务端修复和自动化验证；仍需在 Cherry Studio 将工具外层超时设为 300 秒后完成三路并发、重复搜索、强时效/模糊人物查询和超时后 `get_config_info` 的真实人工复验。300 秒是客户端安全上限，不是性能目标。

## 5. 提交前检查

```bash
uv run ruff check .
uv run pytest
uv run python -m build
git diff --check
```

同时确认：

- 新增环境变量已写入中英文 README。
- Responses 配置已写入中英文客户端指南，并明确端点兼容性、`store=false` 和 Chat 回退方法。
- Cherry Studio 文档明确 300 秒客户端上限、270 秒服务端预算、120 秒单次读取上限及并发等待/重试关系。
- 工具 Schema 变更有自动化测试。
- 错误消息不包含完整 API Key。
- Cherry Studio、Claude Code 和 Codex 的 stdio 启动方式仍然一致。
- 没有实现路线文档明确标记为暂缓的事项。
