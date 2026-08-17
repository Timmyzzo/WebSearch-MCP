# 工作文档：双引擎红线 + 提示词重置 + 全面超越原项目

> **用途**：新开对话时，把本文档作为唯一开工说明。  
> **基准上游**：[GuDaStudio/GrokSearch](https://github.com/GuDaStudio/GrokSearch)  
> **本地仓库**：`D:\code\GrokSearch`（WebSearch MCP / grok-search）  
> **成稿日期**：2026-08-11  
> **优先级**：可用性与不弱于原项目 > 提示词瘦身 > 质量增强 > 可解释错误

---

## 0. 一句话目标

在 **不破坏「Grok 搜 + Tavily 抓/图」双引擎分工** 的前提下，把过重的搜索提示词回退/重置为可稳定调用的形态，并在 **每一项能力上都不弱于原项目，且至少有小幅可感知的超越**。

---

## 1. 产品红线（不可改）

以下架构来自原作者思路，**定为红线**，实现与文档不得偏离：

```text
Claude / 其他 MCP Client
        │  stdio MCP
        ▼
   Grok Search Server
        ├─ web_search  ───► Grok API（AI 联网搜索：广、快、找信源）
        ├─ web_fetch   ───► Tavily Extract（工程化全文抓取：完整、保真）
        └─ web_map     ───► Tavily Map（站点映射 / agentic crawl 入口）
```

### 1.1 分工原则（各取所长）

| 角色 | 负责 | 不负责 |
| --- | --- | --- |
| **Grok** | 广度搜索、快速定位、给出可追溯信源与初答 | 不负责「专业级全文抓取」；不得用 Grok 替代 `web_fetch` 读论文全文 |
| **Tavily** | `Extract` 高保真 Markdown、`Map` 站内结构发现；可选 Search 补结构化结果 | 不负责替代 Grok 的广搜与意图理解 |
| **Claude / 调用方模型** | 按证据标准综合、中文对用户表达、决定何时 search/fetch/map | 不在 MCP 服务端内「替用户写长篇最终风格」除非工具返回需要 |

### 1.2 红线细则

1. **Tavily 是必要能力，不是可有可无装饰。**  
   - `web_fetch` / `web_map` 必须走 Tavily。  
   - 未配置 Tavily 时：明确结构化错误，不得静默空返回。  
   - 论文/长文阅读场景：**必须** 引导用 `web_fetch`，禁止回到「让 Grok fetch 网页」的路径。
2. **`web_search` 只打 Grok Chat Completions**（当前项目已固定，不切 Responses 等协议，除非后续单独开题）。
3. **Fetch 不做「智能摘要抓取」**：Extract 目标是内容保真与结构还原，不是再让模型偷工减料。
4. **Map 保留 agentic crawl 入口**：为「先 map 再 fetch 关键页」留好工具语义与参数。
5. **禁止为了「看起来更强」而单次注入超长系统提示词**，导致超时、漏调工具、或弱于原项目可用性。

### 1.3 明确不做（本阶段）

- 不恢复 Firecrawl 作为主路径（原项目有 Firecrawl 托底；若要对齐「不弱于原项目」的 fetch 成功率，见 §6 可选增强，但不得破坏 Tavily 主路径）。
- 不把客户端本地配置改写工具（如原项目 `toggle_builtin_tools`）加回核心 MCP。
- 不把「强制 7–16 次检索动作」写回 Grok 系统提示。

---

## 2. 两层提示词模型（必须分清）

本仓库里存在 **两层** 提示，下一轮实现不得混为一谈。

### 2.1 层 A：客户端系统提示（给 Claude / 用户侧 Agent）

**身份**：用户与工具编排层。  
**语言规则（用户给定，全文采用）**：

```markdown
## 0. Language and Format Standards  

- **Interaction Language**: Tools and models must interact exclusively in **English**; user outputs must be in **Chinese**.
- MUST ULTRA Thinking in ENGLISH!
- **Formatting Requirements**: Use standard Markdown formatting. Code blocks and specific text results should be marked with backticks. Skilled in applying four or more ````markdown wrappers.

## 1. Search and Evidence Standards  
Typically, the results of web searches only constitute third-party suggestions and are not directly credible; they must be cross-verified with sources to provide users with absolutely authoritative and correct answers.

### Search Trigger Conditions  

Strictly distinguish between internal and external knowledge. Avoid speculation based on general internal knowledge. When uncertain, explicitly inform the user.  

For example, when using the `fastapi` library to encapsulate an API endpoint, despite possessing common-sense knowledge internally, you must still rely on the latest search results or official documentation for reliable implementation.  

### Search Execution Guidelines  

- Use the `mcp__grok-search` tool for web searches  
- Execute independent search requests in parallel; sequential execution applies only when dependencies exist  
- Evaluate search results for quality: analyze relevance, source credibility, cross-source consistency, and completeness. Conduct supplementary searches if gaps exist  

### Source Quality Standards  

- Key factual claims must be supported by ≥2 independent sources. If relying on a single source, explicitly state this limitation  
- Conflicting sources: Present evidence from both sides, assess credibility and timeliness, identify the stronger evidence, or declare unresolved discrepancies  
- Empirical conclusions must include confidence levels (High/Medium/Low)  
- Citation format: [Author/Organization, Year/Date, Section/URL]. Fabricated references are strictly prohibited  

## 2. Reasoning and Expression Principles  

- Be concise, direct, and information-dense: Use lists for discrete items; paragraphs for arguments  
- Challenge flawed premises: When user logic contains errors, pinpoint specific issues with evidence  
- All conclusions must specify: Applicable conditions, scope boundaries, and known limitations  
- Avoid greetings, pleasantries, filler adjectives, and emotional expressions  
- When uncertain: State unknowns and reasons before presenting confirmed facts
```

**落地位置（实现时）**：

1. 写入文档：`docs/CLIENT_SYSTEM_PROMPT.md`（中英说明 + 可复制全文）。  
2. 在 `docs/CLIENT_SETUP.md` / `README.md` 增加「推荐客户端系统提示」链接与粘贴说明。  
3. **不要** 把上述整段作为 Grok `/chat/completions` 的 system 全文反复注入（避免单次注入过大、职责错位）。  
4. 工具名写法：文档中同时给出通用名 `web_search` / `web_fetch` / `web_map` / `get_sources`，并注明 Claude Code 侧可能显示为 `mcp__grok-search__web_search` 等前缀形式。

### 2.2 层 B：Grok 服务端搜索提示（MCP 内，发给 Grok）

**身份**：只服务 `web_search` 上游调用。  
**原则**：

- **短**：显著短于当前 `src/grok_search/prompts.py` 中长文 `SEARCH_PROMPT`。  
- **英**：与层 A 一致，工具/模型交互用英文。  
- **专**：只规定「如何搜、如何给信源、如何组织 content」，不复述整份客户端证据法条。  
- **轻注入**：user 侧可带短时间上下文 + query + 可选 platform；避免每次塞入超大 JSON profile 与领域长文。  
- **对标原项目**：原项目 `utils.search_prompt` 为短指令（多视角 / 深挖 / 引用 / Markdown）。新版本应 **不弱于** 其覆盖面，但用更清晰结构与更可控长度实现。

**建议目标长度**：system 提示控制在约 **1–2 屏**（远小于当前领域细则长文），领域细则改为「按需短附录」或完全下放给客户端层 A。

### 2.3 备份与替换纪律

实现时必须按顺序：

1. **备份**当前提示与构造逻辑：  
   - `src/grok_search/prompts.py` → 例如 `src/grok_search/prompts_legacy_backup.py` **或** `docs/backups/prompts_YYYYMMDD.py`（二选一，优先仓库内可 diff 的路径）。  
2. 从运行路径 **移除** 旧长提示的默认引用（`build_search_messages` 不再使用旧 `SEARCH_PROMPT`）。  
3. 写入新的层 B 短提示 + 新的层 A 文档。  
4. 更新所有依赖旧措辞的测试（`tests/test_search_quality.py` 等）。  
5. 全量测试通过后再谈增强。

---

## 3. 原项目能力基线（超越清单的对照表）

对 [GuDaStudio/GrokSearch](https://github.com/GuDaStudio/GrokSearch) 的能力基线如下。  
**规则：每一行最终状态必须 ≥ 原项目；允许「小幅超越」，禁止「某格变差」。**

| 能力 | 原项目基线 | 本仓库目标（≥ 原项目） |
| --- | --- | --- |
| MCP 形态 | FastMCP stdio，`grok-search` | 保持；跨 Cherry Studio / Claude Code / Codex |
| `web_search` | Grok stream Chat Completions | 同协议；更稳的流完整性、错误结构化、预算/并发 |
| 搜索广度/速度 | 依赖 Grok 广搜，prompt 鼓励 5 视角 + 2 深挖 | 保留「广而快」导向，**禁止**硬编码导致 MCP 超时的检索楼层 |
| 时间上下文 | 每次注入本地时间 | 保留；可优化为始终短注入 |
| `get_sources` | session 缓存信源 | 保留；TTL/去重/标题解析增强可保留 |
| `web_fetch` | Tavily Extract，失败可 Firecrawl | **主路径 Tavily**；错误明确；全文保真优先于摘要 |
| `web_map` | Tavily Map 参数齐全 | 参数与语义不弱于原项目 |
| 配置诊断 | `get_config_info` | 保留并结构化 |
| 模型切换 | `switch_model` 持久化 | 保留 |
| 规划工具 | 多阶段 plan_* | 可保留为可选；**不得**强制搜索前必须 plan |
| 重试 | Tenacity，默认约 3 | 可配置；默认值需兼顾可用性（勿默认拖死客户端） |
| 多 Key / 熔断 | 原项目较弱 | 本仓库 P2 能力应保留（这是超越点） |
| 统一错误协议 | 原项目多为纯文本/空 | P4 三态应保留（超越点），但 schema 不得导致客户端无法调工具 |
| 客户端系统提示 | 文档化不足 | **新增** §2.1 官方推荐提示（超越点） |

### 3.1 「不弱于原项目」的硬验收

新开对话实现完成后，至少满足：

1. **可调用**：stdio 初始化、`list_tools`、核心工具可调用。  
2. **可搜索**：配置合法时 `web_search` 返回 `content` + `session_id`，不无故空。  
3. **可溯源**：`get_sources` 能取回信源。  
4. **可抓取**：配置 Tavily 后 `web_fetch` 返回正文 Markdown（论文 URL 场景作为人工验收重点）。  
5. **可映射**：`web_map` 返回 URL 列表结构。  
6. **可诊断**：`get_config_info` 可测连通性。  
7. **超时可控**：默认路径下，简单查询不应稳定打满客户端 300s；服务端总预算机制保留。  
8. **测试**：`pytest` 全绿；对提示词相关断言与新备份策略一致。

---

## 4. 当前仓库状态（开工前快照）

> 供新对话快速对齐，避免重复踩坑。

### 4.1 已具备（应保留的强化）

- 模块化：`clients/grok.py`、`clients/tavily.py`、tools 分层  
- Tavily 多 Key、熔断、每 Key 并发 1  
- Grok 并发上限、单次总预算（约 270s）  
- 统一 `success` / `partial_success` / `error`  
- 信源缓存 TTL、URL 规范化去重  
- 流式响应较完整校验、可配置重试  
- `<think>` 块清理（若仍在工作区）  

### 4.2 已暴露的问题（本工作文档要解决）

1. **Grok 侧提示过长/过重** → MCP 搜索易超时、体验弱于原项目「清爽」。  
2. **深度楼层曾被写死** → 与「广而快」产品定位冲突（已部分回退为自适应，但仍需按本文重置）。  
3. **客户端证据标准未产品化** → 大佬场景是「Grok 给信源，Claude 读信源总结」；需要官方客户端系统提示，而不是全塞进 Grok。  
4. **Tavily 必要性表达不足** → 文档与工具描述须强调 fetch/map 必经 Tavily，论文场景禁止 Grok 代 fetch。

### 4.3 关键路径（实现时优先改）

| 路径 | 动作 |
| --- | --- |
| `src/grok_search/prompts.py` | 备份后重置层 B；精简 `build_search_messages` |
| `src/grok_search/clients/grok.py` | 确认只引用新提示构造；保持 Chat Completions |
| `src/grok_search/tools/web.py` | 工具 description 对齐红线分工；`web_search` 可调、直白 |
| `src/grok_search/tools/*` | fetch/map 错误文案强调 Tavily 配置 |
| `tests/test_search_quality.py` 等 | 跟新提示词重写断言 |
| `docs/CLIENT_SYSTEM_PROMPT.md` | **新建**：层 A 全文 |
| `docs/CLIENT_SETUP.md` / `README.md` | 链接层 A；强调双引擎与 Tavily 必要 |
| `docs/backups/` 或 `*_legacy_backup.py` | 旧提示备份落盘 |

---

## 5. 新对话推荐实现顺序（PR 粒度）

### PR-1：提示词备份与层 B 重置（必须先做）

- [ ] 备份当前 `prompts.py` 全文到约定备份路径  
- [ ] 删除/停用运行路径上的冗长 `SEARCH_PROMPT` 与过重 profile 注入  
- [ ] 实现短英文 Grok system prompt（对标原项目能力，不弱）  
- [ ] `build_search_messages`：短 system + 短 user（时间 + query + platform + 可选极简 supplemental）  
- [ ] 更新单元测试；全量 `pytest` 通过  

**层 B 内容要点（实现约束，不必照抄长文）：**

- 英文思考与工具交互  
- 广搜、必要时多视角、关键结论附 URL/来源  
- 简单问题尽快答；复杂问题再加深（软引导，非法强制 7–16 次）  
- 不把网页全文抓取当自己的职责；完整页面交给 fetch 工具链  
- 输出 Markdown；信源集中在 Sources/References 段，便于 `split_answer_and_sources`  

### PR-2：层 A 产品化（客户端系统提示）

- [ ] 新增 `docs/CLIENT_SYSTEM_PROMPT.md`，内容为用户给定全文（可加极短中文导读）  
- [ ] README / CLIENT_SETUP 增加「推荐粘贴到 Claude/Cherry Studio 系统提示」  
- [ ] 工具命名兼容说明（`mcp__grok-search__*`）  
- [ ] 明确论文阅读工作流：`web_search` 定位 → `web_fetch` 全文 →（可选）`web_map` 站内扩展 → 客户端按证据标准综合  

### PR-3：工具语义与 Tavily 红线加固

- [ ] `web_search` description：Grok 广搜与信源，不用于全文抓取  
- [ ] `web_fetch` description：Tavily Extract，论文/文档全文场景首选  
- [ ] `web_map` description：Tavily Map，站内发现  
- [ ] 无 Tavily Key 时错误信息可操作（如何配置 `TAVILY_API_KEY` / `TAVILY_API_KEYS`）  
- [ ] 确认 `extra_sources` 与 Tavily Search 的关系：**可保留为增强**，但不得削弱「fetch/map 必 Tavily」叙事  

### PR-4：不弱于原项目的回归与小幅超越验收

- [ ] 对照 §3 表格逐项勾选  
- [ ] 至少一组人工场景：  
  1. 简单事实搜索（应快）  
  2. 官方文档/版本类问题  
  3. 论文或长文 URL 的 `web_fetch` 完整度  
  4. 文档站 `web_map`  
- [ ] 记录「相对原项目的超越点」列表（哪怕很小）：例如多 Key、结构化错误、总预算、客户端官方 system prompt、信源解析增强等  

### PR-5（可选，仅当不伤害红线时）

- [ ] Firecrawl 仅作 fetch 托底是否引入：默认 **不做**；若验收显示 Tavily 失败率过高，另开设计，不得默认依赖  
- [ ] 规划工具是否进一步降权或移出默认工具列表：需单独决策，默认保留但不强制  

---

## 6. 超越原项目的最小增量策略

不要用「更长 prompt」冒充超越。优先这些 **可证明** 的增量：

1. **可靠性**：预算、并发、重试、熔断、流完整性 > 原项目  
2. **可解释错误**：P4 结构化错误 > 原项目空串/纯文本  
3. **Tavily 工程化**：多 Key、Key 指纹日志、Extract/Map 专用 > 原项目单 Key 简实现  
4. **客户端工作流产品化**：官方层 A 系统提示，明确「Grok 找源、Tavily 取文、Claude 综合」  
5. **信源工程**：session 缓存、去重、更多标题样式解析  
6. **跨客户端**：去掉改本地配置的工具，文档覆盖多客户端  

若某改动会让「简单搜索更慢 / 更易超时 / 更难调用」，则 **视为回归，必须回滚**，哪怕文案更「专业」。

---

## 7. 新对话开场白（可直接复制）

把下面整段粘贴到新对话即可开工：

```text
请阅读并严格执行：docs/WORK_PLAN_DUAL_ENGINE_PROMPT_RESET.md

红线：
- web_search → Grok
- web_fetch → Tavily Extract
- web_map → Tavily Map
- Tavily 对 fetch/map 必要；论文全文禁止用 Grok 代替 fetch

任务：
1. 备份并移除当前冗长 Grok 搜索提示词（prompts.py）
2. 实现短英文 Grok system prompt（层 B），不弱于 GuDaStudio 原项目搜索能力
3. 新增客户端系统提示文档（层 A），内容为工作文档 §2.1 给定全文
4. 工具描述与文档对齐双引擎分工
5. 更新测试，全量 pytest 通过
6. 对照工作文档 §3 给出「不弱于原项目 + 超越点」清单

约束：
- 禁止单次注入超长系统提示导致 MCP 超时
- 禁止强制 7–16 次检索楼层
- 任何能力不得弱于原项目
```

---

## 8. 完成定义（Definition of Done）

同时满足才算本工作阶段完成：

- [ ] 旧提示已备份且默认路径不再加载  
- [ ] 层 A 文档已存在且 README/安装文档可发现  
- [ ] 层 B 短提示已接入 `GrokClient.search`  
- [ ] 双引擎红线在 README 工具说明中清晰可见  
- [ ] `pytest` 全绿  
- [ ] §3 对照表无「弱于原项目」项  
- [ ] 至少列出 3 条可验证的超越点  

---

## 9. 参考

- 上游：https://github.com/GuDaStudio/GrokSearch  
- 概念与动机存档：`docs/Original MCP Concept Post.md`  
- 既有路线图：`docs/DEVELOPMENT_ROADMAP.md`（本文优先于其中与提示词冲突的旧表述）  
- 超时与并发背景：`docs/SEARCH_TIMEOUT_AND_CONCURRENCY_TASK.md`  
- 当前实现：`src/grok_search/prompts.py`、`src/grok_search/tools/web.py`、`src/grok_search/clients/grok.py`

---

**文档结束。** 新开对话时以本文为唯一主说明；若与旧 roadmap 冲突，以本文红线与提示词分层为准。
