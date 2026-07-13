# WebSearch MCP 外部项目实现分析

本文记录 2026-07-13 对 `docs/Original MCP Concept Post.md` 所列项目、介绍内容和官方协议资料的代码级审计。分析以实际默认分支代码为准，不把 README 宣传语当作实现事实。

## 1. 审计范围与可访问性

| 对象 | 审计版本 | 可访问性 | 许可证 |
| --- | --- | --- | --- |
| [BlueOcean223/grok-search](https://github.com/BlueOcean223/grok-search) | `main` @ `2f6fee5` | Git、GitHub API 和完整代码可访问；4 组 Node 测试通过 | MIT；同时保留 2025 GuDaStudio 版权声明 |
| [GuDaStudio/GrokSearch](https://github.com/GuDaStudio/GrokSearch) | `main` @ `afcdbcc`，并核对 `dev`、`grok-with-tavily`、`grok-with-tavily-clean` 文件树 | Git、GitHub API 和完整代码可访问；可构建，但仓库无自动化测试 | MIT |
| [linux.do 项目介绍帖](https://linux.do/t/topic/1356321) | 工作区文档保存的完整首帖正文与截图 | 在线 JSON 端点返回 HTTP 403；本地快照完整可读 | 文章不是代码许可证依据 |
| [xAI 官方文档](https://docs.x.ai/developers/rest-api-reference/inference/chat) | 2026-07-13 在线版本、`llms.txt`、Web Search 与 Citations 章节 | 可访问 | 官方文档仅用于确认协议，不复制其示例代码 |

没有 GitHub 仓库因访问失败而缺失。参考仓库克隆在工作区外的临时审计目录，没有把第三方源码加入本仓库。

## 2. 能力对比矩阵

| 维度 | BlueOcean223/grok-search | GuDaStudio/GrokSearch | WebSearch MCP 审计前 | 本次决策 |
| --- | --- | --- | --- | --- |
| 形态 | Node Agent Skill，三个命令脚本 | Python FastMCP stdio | Python FastMCP stdio | 保持 MCP，不改为 Skill |
| Grok 协议 | 仅 Responses；xAI/兼容端点显式 `web_search`，OpenRouter 使用专用工具类型 | Chat Completions 流式请求，依赖模型或中转站自行搜索 | Chat Completions 流式请求，完整流校验 | 增加可选 Responses，默认仍为 Chat |
| 搜索可审计性 | 解析 citations、annotations、`web_search_call`/`x_search_call` | 主要从回答尾部解析链接，不能证明真实搜索 | 从回答尾部解析来源，残缺流不缓存 | Responses 模式解析结构化引用与搜索轨迹 |
| Tavily 关系 | 与 Grok 并行，结果事后合并；Grok 未读取这些候选 | 与 Grok/Firecrawl 并行，结果事后合并 | Tavily 先给候选，Grok 在同一次最终综合中核验 | 保持当前证据融合方式 |
| Grok 失败语义 | 特定额度错误可用 Tavily/Firecrawl 原始结果构造降级答案 | 异常常被吞掉为空字符串，仍可能返回空内容 | Grok 失败始终 `error`，Tavily 不可替代 | 明确拒绝外部降级答案语义 |
| Fetch/Map | Tavily → Firecrawl → Direct Fetch；Map 有 Direct fallback | Tavily/Firecrawl，历史上 Grok fetch | 仅 Tavily Extract/Map | 不引入 Firecrawl、Direct Fetch 或浏览器链路 |
| 重试 | 单请求固定次数、指数退避、`Retry-After`；无调用级总预算 | Tenacity；配置名与实际尝试语义存在偏差 | 默认最多 12 次真实请求，统一总预算、可配置内嵌错误码和终止原因 | Responses 评估后未采用 |
| 并发 | `Promise.all` 并行 provider；无进程级 Grok/Key 限流 | `asyncio.gather`；无共享并发治理 | Grok 最大 2；Tavily 每 Key 最大 1 | 不回退 |
| 熔断/多 Key | 单 Tavily Key，无 Key/服务级熔断 | 单 Key，无服务级熔断 | P2 四状态、Key/服务熔断、半开探测 | 不回退 |
| 缓存 | 完整输出可落盘，30 天清理 | 来源 LRU 256；模型列表永久缓存，失败可缓存空列表 | 来源 LRU 256；模型列表永久缓存成功结果 | 来源 TTL 1 小时；模型目录 TTL 5 分钟 |
| 长内容 | stdout preview，完整内容写本地文件 | 无统一结构化截断 | 工具返回稳定结构 | 不默认落盘搜索正文，避免敏感数据扩散 |
| 测试 | 4 组 Node fixture/CLI 测试和公开 benchmark | 无测试 | 141 个 Python 测试 | 增至 152 个，含 Responses/TTL/stdio |
| 公共协议 | 非 MCP，无 P4 三态 | 多处 `output_schema=None`，错误常为普通文本/空值 | 固定 MCP Schema 与 P4 三态 | 完全保留 |

## 3. BlueOcean223/grok-search

### 3.1 核心设计思路

该项目把搜索、抓取、站点映射拆成独立 Skill 脚本。搜索主通道使用 `/responses` 和服务端 `web_search`，Tavily、Firecrawl 作为并行的独立信源通道。它强调可复现实验、tool trace、citations、输出预览和完整结果落盘。

### 3.2 实际实现

- `scripts/lib/grok-responses.js` 构造 Responses 请求，解析 `output_text`、嵌套 annotations、top-level citations 和 search tool call。
- `scripts/search.js` 用 `Promise.all` 并行 Grok 与额外 provider；额外结果没有进入 Grok input。
- `scripts/lib/providers.js` 实现固定次数重试、`Retry-After`、Tavily/Firecrawl/Direct provider，但没有当前项目的多 Key 健康状态、服务熔断或总预算。
- `scripts/lib/output.js` 对长结果返回 preview，并将完整内容写入用户缓存目录，默认保留 30 天。
- `tests/responses.test.js` 覆盖 Responses body、citations、search trace、OpenRouter 工具类型和来源去重；CLI fixture 覆盖参数与错误对象。
- 公开 benchmark 将 Responses、Chat、Tavily、Brave 等路径分组比较，结论支持“显式工具协议比只靠提示词更可审计”。

### 3.3 值得吸收

- 把真实搜索能力绑定到协议级 `web_search`，而不是假设 Chat 模型会因提示词自动联网。
- 同时解析完整 citations、inline annotations 和 search/open-page trace。
- 让 Responses 成为可选能力，不强迫所有 OpenAI 兼容中转站立即迁移。
- 对 OpenRouter Responses 不再追加 Chat 模式的 `:online` 后缀。

### 3.4 不采用或不适合本项目

- “Grok 额度失败时用 Tavily/Firecrawl 原始结果生成降级答案”违反本项目 P4：Grok 失败必须为 `error`。
- Tavily/Firecrawl 与 Grok 只并列返回，Grok 没有核验额外结果；本项目继续采用“候选证据进入 Grok 最终综合”。
- Firecrawl、Direct Fetch、浅层 Direct Map 增加新的抓取语义和维护面，不符合当前仅 Tavily 的路线。
- 完整搜索正文默认落盘会扩大敏感内容、版权材料和凭据回显的持久化风险。
- 没有调用级 270 秒预算、Grok 进程级并发 2、Tavily 每 Key 并发 1 和 P2 熔断语义。
- 其简短 Prompt 倾向“按问题需要尽快停止”，不满足本项目固定的 5 个广度视角加 2 个深挖方向下限。

### 3.5 许可证与复用风险

仓库为 MIT，允许复用，但需保留版权与许可证。本次只采用协议与解析思路，Python 实现按当前项目结构重新设计，没有复制大段 JavaScript。若未来直接移植具体实现，应在相应文件或 NOTICE 中保留 BlueOcean 与 GuDaStudio 的版权声明。

## 4. GuDaStudio/GrokSearch

### 4.1 核心设计思路

该项目是当前路线的早期 MCP 参考：用 Grok Chat 负责搜索答案，Tavily/Firecrawl 补充来源，提供 `web_search`、`get_sources`、`web_fetch`、`web_map`、配置诊断、模型切换和多阶段规划工具。

### 4.2 实际实现

- `providers/grok.py` 每次创建 `httpx.AsyncClient`，向 `/chat/completions` 发流式请求，用 Tenacity 重试。
- 流解析把收到的 delta 拼接成字符串，但未要求 `[DONE]` 或最终 `finish_reason`，残缺流可能被当作成功。
- `server.py` 用 `asyncio.gather` 并行 Grok、Tavily、Firecrawl；`_safe_*` 捕获所有异常并返回空值。
- Tavily/Firecrawl 结果在 Grok 完成后才合并进缓存，不进入 Grok 最终答案综合。
- `SourcesCache` 是最大 256 项的进程内 LRU，没有 TTL；模型列表缓存也没有 TTL。
- 六个规划工具把一次搜索拆成较多 MCP 往返；工具说明还要求搜索前先规划。
- 仓库没有测试目录；只能确认包可构建。

### 4.3 值得吸收

- MCP stdio、稳定工具名、来源会话、配置诊断、模型切换和 Windows/Codex 生命周期兼容，是当前项目已继承并大幅强化的基础。
- 来源缓存需要有容量上限；本次进一步增加 TTL。
- 运行时日期/时区上下文和来源尾部解析仍有兼容价值。

### 4.4 不采用或不适合本项目

- 捕获异常后返回空字符串会掩盖真实失败，违反 P4。
- Chat 提示词不能证明实际搜索，且流完整性不足。
- 全部 provider 并行但不做证据融合，容易把互不一致的结果交给上层模型自行猜测。
- 无共享连接池、总预算、并发限制、多 Key 状态和熔断。
- 强制多阶段规划增加串行延迟和客户端耦合；本项目保留规划工具但不设为搜索前置。
- `toggle_builtin_tools` 修改客户端本地配置，不属于通用 MCP 服务职责。

### 4.5 许可证与复用风险

仓库为 MIT。当前项目历史上已从其工具形态和部分基础结构演进，项目许可证兼容。本次没有从该仓库复制新代码；新增实现基于当前模块化、P2/P3/P4 约束重新编写。

## 5. xAI 官方协议事实

官方资料确认：

- Responses API 是当前推荐的文本与工具协议。
- `tools: [{"type": "web_search"}]` 让模型执行实时搜索和页面浏览。
- Responses 默认会在 xAI 服务端保存请求/响应 30 天；`store: false` 可关闭该存储。
- `response.citations` 默认返回搜索过程中遇到的全部 URL；`output_text.annotations` 提供结构化 inline citation。
- 同步响应有 `status`，完整结果应为 `completed`；`incomplete`/`in_progress` 不能当作完整答案。
- `max_tool_calls` 可限制单次响应的工具调用数量。

因此本项目没有直接照搬参考仓库的 `max_turns` 字段，而是采用官方当前文档中的 `max_tool_calls`。

## 6. 当前项目差距与优先级

| 改进 | 收益 | 复杂度 | 兼容风险 | 维护成本 | 结论 |
| --- | --- | --- | --- | --- | --- |
| 可选 Responses + 显式 `web_search` | 很高：真搜索、可审计引用 | 中 | 中；部分中转站不支持 | 中 | 评估后移除；产品仅保留 Chat |
| citations/search trace 进入 `get_sources` | 高：来源不再只依赖回答尾部 | 中 | 低 | 低 | 随 Responses 路径移除 |
| `store=false` | 高：避免官方默认 30 天保存 | 低 | 低 | 低 | Responses 专属，未采用 |
| 来源会话 TTL | 中：长期进程内存与陈旧会话有界 | 低 | 低 | 低 | 本次实现，1 小时 |
| 模型目录 TTL | 中：避免永久陈旧 | 低 | 低 | 低 | 本次实现，5 分钟 |
| Responses 域名/X 过滤公共参数 | 中 | 中 | 高：会改变 MCP Schema | 中 | 暂不实现 |
| Firecrawl/Direct Fetch | 中 | 高 | 高：改变抓取语义 | 高 | 拒绝 |
| Tavily 替代 Grok 答案 | 表面可用性高 | 低 | 不可接受：违反 P4 | 中 | 拒绝 |
| 浏览器、RAG、向量库、任务队列 | 当前证据不足 | 很高 | 高 | 很高 | 拒绝 |

## 7. 本次采用的实现

- 运行时固定使用流式 `/v1/chat/completions`，删除协议选择环境变量和 Responses 请求/解析路径。
- 中转站只需兼容 `/v1/chat/completions` 与 `/v1/models`。
- Chat 请求继续服从可配置真实请求次数（默认 12）、270 秒总预算、Grok 并发 2、取消释放、错误分类和 P4 组合语义。
- 来源会话默认 1 小时过期且最多 256 项；模型目录成功结果缓存 5 分钟，失败不缓存。

## 8. 明确拒绝的替代设计

- 不提供 Responses 可选开关：产品只面向 Chat Completions 中转站，避免维护第二套协议语义。
- 不在 Grok 失败时返回 Tavily 答案：保持“Grok 失败、Tavily 成功仍为 `error`”。
- 不把 Tavily 改回并列展示：候选证据必须由 Grok 核验并综合。
- 不新增 Firecrawl、Direct Fetch、浏览器自动化或新的抓取服务。
- 不把六阶段规划变成 `web_search` 前置条件。
- 不默认把完整搜索正文写入磁盘。
- 不新增域名过滤、X handle 等 MCP 参数，避免公共 Schema 变更。

## 9. 自动化验证

新增测试覆盖来源会话 TTL/LRU、模型目录 TTL 刷新，以及 Chat 流中断、超时、取消、共享槽位释放和 stdio 错误后存活。

参考仓库测试结果：BlueOcean 4 组 Node 测试通过；GuDaStudio 无自动化测试但构建成功。Chat-only 收敛后的当前项目验证为 144 个 pytest 全部通过，Ruff、构建和 diff check 全部通过。
