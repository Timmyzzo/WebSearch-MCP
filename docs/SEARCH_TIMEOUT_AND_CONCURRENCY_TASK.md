# WebSearch MCP 搜索超时与并发治理任务书

## 1. 背景

Cherry Studio 实际验收中，`get_config_info`、`web_fetch`、`web_map`、结构化错误和错误后进程存活均正常，但 `web_search` 出现大面积 MCP `-32001: Request timed out`。

当前组合为：

- Grok 模型：`grok-4.20-multi-agent-xhigh`。
- 所有搜索至少覆盖 5 个独立视角，并深挖至少 2 个方向。
- 普通研究通常包含 7–12 个检索动作，增强研究通常包含 10–16 个检索动作。
- 单次 Grok HTTP 读取超时默认 120 秒，可通过环境变量调整。
- 可恢复错误默认最多真实调用 12 次。
- Cherry Studio MCP 工具外层超时计划调整为 300 秒。

如果没有整次调用的总时间预算，最坏情况可能超过 12 × 120 秒并叠加退避等待，远大于 Cherry Studio 的 300 秒。因此，仅把客户端超时改成 300 秒不能独立解决问题。

## 2. 已确认的根因与约束

### 2.1 超时层级不匹配

- Cherry Studio 的 300 秒是 MCP 工具调用外层等待上限。
- WebSearch MCP 必须在该上限前主动完成或返回结构化错误。
- 建议整次 `web_search` 服务端墙钟预算为 240–270 秒，默认建议 270 秒。
- 至少预留约 30 秒给 MCP 序列化、进程调度、客户端传输和误差。
- 达到服务端预算时，应取消尚未完成的上游请求并返回稳定、可重试的结构化超时错误，不能等待客户端先产生裸 `-32001`。

### 2.2 深度要求不能机械串行化

必须继续保留不弱于原项目的搜索能力下限：

- 至少 5 个真正不同的广度视角。
- 至少选择 2 个高价值或高不确定性方向继续深挖。
- 微小关键词改写不能冒充不同视角。
- 简单问题仍做深度核验，但最终答案保持简洁。

这些要求是研究覆盖目标，不应被实现为无界循环，也不应强制所有检索动作串行执行。应优先利用模型自身的并行搜索能力，在总时间预算内完成覆盖、深挖和综合。

### 2.3 Grok 并发上限

- 同一 MCP 进程内，正在执行的 Grok `/chat/completions` 请求总数不得超过 2。
- 限制作用于所有并发 `web_search` 调用和所有真实重试。
- 等待 Grok 并发槽位的时间必须计入整次 `web_search` 墙钟预算。
- 调用被取消、超时、异常或流中断时必须可靠释放并发槽位。
- 不得因重试绕过并发限制。
- 并发限制应使用进程级共享、异步安全且可测试的机制，例如 `asyncio.Semaphore(2)` 或等价抽象。
- 不要求控制 Grok 模型服务内部不可见的 Agent 数量；这里只限制 WebSearch MCP 发出的真实 HTTP 请求数。

### 2.4 Tavily 每 Key 并发上限

- 每个 Tavily API Key 同时最多执行 1 个真实请求。
- Search、Extract、Map 必须共享同一个 Key 并发状态，与现有共享健康状态一致。
- 多个健康 Key 可以分别承担一个并发请求，因此服务总 Tavily 并发上限最多等于当前可用 Key 数量。
- 同一 Key 忙碌时，优先选择其他健康且空闲的 Key。
- 所有健康 Key 都忙碌时，可以在当前工具总预算内等待最早可用 Key，不能把“忙碌”误判为限流、额度耗尽或 Key 失效。
- 等待取消、请求异常、超时和熔断切换时必须释放 Key 槽位。
- 不能破坏现有轮询、公平性、`healthy` / `cooldown` / `quota_exhausted` / `invalid` 状态、Key 级熔断、服务级熔断和半开探测。
- Tavily 免费额度是否为每月 1000 次不作为代码中的硬编码事实；并发限制的目的主要是避免单 Key 同时请求和不可控消耗。

## 3. 目标行为

### 3.1 Cherry Studio 超时建议

Cherry Studio MCP 工具超时设置为 300 秒是合理的验收起点，但必须与服务端主动预算配合：

```text
Cherry Studio tool timeout: 300 seconds
WebSearch MCP total web_search budget: 270 seconds recommended
Grok single-attempt read timeout: must not independently exceed remaining total budget
```

客户端 300 秒不代表每次搜索都应运行接近 300 秒。简单问题仍应尽快完成；270 秒只是服务端硬上限。

### 3.2 重试语义

- `GROK_MODEL_MAX_ATTEMPTS=12` 表示默认最多 12 次真实请求，并允许配置为任意正整数。
- 每次重试前必须检查剩余总时间；剩余时间不足以完成一次合理请求时应停止重试。
- 认证错误、参数错误、模型不存在和模型无权限继续立即停止。
- 模型暂时不可用、429、5xx、连接错误、读取超时、流中断，以及 `GROK_RETRYABLE_UPSTREAM_CODES` 列出的 HTTP 200 内嵌临时错误仍可重试，但不得突破总预算。
- `Retry-After` 只有在不突破剩余总预算时才等待。

### 3.3 错误消息与诊断

修复“实际只尝试 1 次，却提示已用尽重试次数”的文案问题：

- 真正达到尝试次数上限：说明“已用尽最大尝试次数”。
- 因不可重试错误提前停止：说明“因不可重试错误提前停止”。
- 因整次墙钟预算耗尽：说明“搜索总时间预算已耗尽”。
- 因等待并发槽位超时：说明“等待上游并发槽位时预算耗尽”。

`grok_error` 和 `error_detail.diagnostics` 应保留兼容字段，并补充必要的脱敏信息：

- `termination_reason`
- `configured_max_attempts`
- `actual_attempts`
- `elapsed_ms`
- `budget_ms`
- `queue_wait_ms`
- `last_error_type`
- `last_http_status`
- `last_upstream_code`

不得包含 API Key、Authorization、可能回显凭据的响应正文或 traceback。

### 3.4 P4 组合语义保持不变

- Grok 成功、Tavily 失败：`partial_success`。
- Grok 失败、Tavily 成功：`error`。
- Tavily 不能替代 Grok 最终答案。
- 不得为了规避超时把 Tavily 单独结果伪装为 Grok 答案或 `partial_success`。
- Grok 有效答案没有来源仍为 `success`。
- 错误只结束当前调用，MCP 进程继续存活。

## 4. 建议配置

可以新增以下内部环境变量；不得改变现有 MCP 工具公共参数和返回 Schema：

| 变量 | 建议默认值 | 说明 |
| --- | ---: | --- |
| `GROK_MAX_CONCURRENCY` | `2` | 当前 MCP 进程最多同时发出的 Grok HTTP 请求数。 |
| `TAVILY_PER_KEY_MAX_CONCURRENCY` | `1` | 每个 Tavily Key 的真实请求并发上限。 |
| `WEB_SEARCH_TOTAL_TIMEOUT` | `270` | 单次 `web_search` 的服务端总墙钟预算，单位秒。 |

如果实现者认为已有变量命名体系需要调整，可以选择等价名称，但必须更新中英文文档和测试。

## 5. 实现边界

- 不改变 `web_search`、`get_sources`、`web_fetch`、`web_map`、`get_config_info`、`switch_model` 的公共参数。
- 不改变 P4 三态和规范错误对象基本 Schema。
- 不引入持久化任务队列、外部消息队列、浏览器自动化、RAG、向量数据库或新的抓取服务。
- 不引入无界 Agent 循环。
- 不把 Cherry Studio 私有能力作为服务端正确运行的前提。
- 不删除 P2、P3、P4 的兼容字段。
- 不破坏流式响应完整性校验；残缺内容不得返回、缓存或用于来源提取。

## 6. 自动化测试要求

至少增加以下可观察行为测试：

1. 三个并发 Grok 请求中，任意时刻实际进入 HTTP 层的请求不超过 2。
2. Grok 请求成功、失败、取消和流中断后都会释放并发槽位。
3. 重试仍受 Grok 并发上限约束。
4. 同一 Tavily Key 的 Search、Extract、Map 并发不超过 1。
5. 不同健康 Tavily Key 可以各执行一个并发请求。
6. 忙碌 Key 不会被错误标记为 cooldown、quota_exhausted 或 invalid。
7. Tavily 请求完成、失败、取消和熔断后会释放 Key 槽位。
8. `web_search` 达到服务端总预算时返回结构化错误，而不是空成功。
9. 等待 Grok/Tavily 槽位的时间计入总预算。
10. 剩余预算不足时不再开始新的 Grok 重试。
11. 不可重试错误只尝试 1 次，并返回“提前停止”语义和正确诊断。
12. 尝试次数真正耗尽时返回“尝试次数耗尽”语义。
13. Grok 失败而 Tavily 成功仍为 `error`。
14. 超时和错误后 stdio MCP 进程仍可继续调用 `get_config_info`。
15. 并发调用的 session、来源、尝试计数和诊断互不串线。

## 7. 文档要求

更新：

- `README.md`
- `docs/README_EN.md`
- `docs/DEVELOPMENT.md`
- `docs/DEVELOPMENT_ROADMAP.md`
- `docs/CLIENT_SETUP.md`
- `docs/CLIENT_SETUP_EN.md`

文档必须说明：

- Cherry Studio 建议将 MCP 工具超时设置为 300 秒。
- 服务端默认在约 270 秒内主动结束。
- Grok 并发默认最多 2。
- Tavily 每 Key 并发默认最多 1。
- 300 秒是安全上限，不是性能目标。
- 单次尝试超时、总预算、最大尝试次数和并发等待之间的关系。

## 8. 完成验证

完成后运行：

```text
pytest
ruff check .
python -m build
git diff --check
```

同时扫描：

- API Key 与 Authorization 泄露。
- 旧仓库地址与旧安装链接。
- 新增诊断是否包含响应正文、traceback 或内部对象表示。

最后创建独立提交并推送到 `origin/main`，确认工作区干净且 `main` 与 `origin/main` 完全同步。

## 9. 人工复验重点

在 Cherry Studio 将 MCP 工具超时设为 300 秒后，至少复验：

1. 一个简单官方文档查询。
2. 一个 `extra_sources>0` 的强时效查询。
3. 一个模糊人物或公开记录深度查询。
4. 两个并发 `web_search`。
5. 第三个并发 `web_search` 是否排队且不导致前两个异常。
6. 三次重复搜索是否都在 300 秒内返回业务层成功或结构化错误。
7. 超时错误后 `get_config_info` 是否仍成功。
8. `grok_error` 的实际尝试次数、终止原因和文案是否一致。

## 10. 实现完成记录（2026-07-13）

本任务书要求的服务端实现与自动化测试已完成：

- `WEB_SEARCH_TOTAL_TIMEOUT=270`：单次 `web_search` 使用调用级单调时钟总预算；Tavily 补充、Grok 槽位、真实 HTTP、完整流读取、退避和 `Retry-After` 都计入预算。
- Grok 单次读取上限默认 120 秒并可配置，但每次请求会裁剪到当前剩余总预算；剩余预算不足时不开始新重试。
- `GROK_MAX_CONCURRENCY=2`：进程级共享 Grok 异步槽位限制器，每次真实重试重新获取槽位。
- `TAVILY_PER_KEY_MAX_CONCURRENCY=1`：Search、Extract、Map 共用 Key 占用状态；不同健康 Key 可并发，同一 Key 忙碌时优先选择其他 Key，全部忙碌时在工具预算内等待。
- Grok 与 Tavily 槽位在成功、失败、取消、异常、总预算超时、流中断和熔断切换路径中释放。
- 上游协议固定为流式 `/chat/completions`；流中断、空内容和读取超时都按残缺结果处理，不返回或缓存部分答案。
- Grok 终止诊断区分 `max_attempts_exhausted`、`non_retryable_error`、`total_budget_exhausted`、`concurrency_queue_timeout`，并补充 `configured_max_attempts`、`actual_attempts`、`elapsed_ms`、`budget_ms`、`queue_wait_ms` 及最后错误分类。
- P2 轮询和健康状态、Key/服务级熔断、半开探测、`Retry-After`，P3 单模型/最多五次真实请求/流完整性，以及 P4 三态和 Grok/Tavily 组合语义均保留。
- 自动化测试覆盖本任务书第 6 节要求，包括超时后 stdio 进程继续调用 `get_config_info`、并发会话/来源/诊断隔离，以及 Grok 失败而 Tavily 成功仍为 `error`。

## 11. 待执行的 Cherry Studio 人工复验

自动化实现完成不替代真实客户端复验。发布后在 Cherry Studio 将 MCP 工具外层超时设为 300 秒，并保持服务端 `WEB_SEARCH_TOTAL_TIMEOUT=270`，执行：

1. 简单官方文档查询，确认明显早于 300 秒完成。
2. `extra_sources>0` 的强时效查询，确认 Tavily 候选进入 Grok 综合且 P4 状态正确。
3. 模糊人物或公开记录深度查询，确认至少 5 个独立视角和 2 个深挖方向仍生效。
4. 同时发起两个 `web_search`，确认均正常执行。
5. 再发起第三个 `web_search`，确认其排队且不使前两个异常。
6. 连续三次重复搜索，确认每次都在 300 秒内返回业务层成功、部分成功或结构化错误，而不是裸 `-32001`。
7. 制造或等待一次结构化总预算错误后调用 `get_config_info`，确认 MCP 进程继续存活。
8. 核对 `grok_error`/`error_detail.diagnostics` 的实际尝试次数、终止原因、耗时、预算、排队时间和文案一致，且没有 Key、Authorization、响应正文或 traceback。
