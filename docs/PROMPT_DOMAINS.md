# Grok 层 B 领域细则（按需注入）

领域细则拆成小文档，放在 `src/grok_search/prompt_domains/*.md`。  
**基座 system 提示**只内置领域目录说明；**命中领域时**才把对应 Markdown 追加到 system，避免简单问题拖慢。

## 机制

1. `prompts.py` 基座提示含「Domain addenda (on-demand)」目录。  
2. `match_domain_ids(query)` 用关键词匹配，最多注入 **3** 个领域。  
3. 命中时 system 追加 `## Active domain addenda` + 各领域全文；user JSON 带 `active_domains`。  
4. 未命中时只发基座提示（含目录，无领域正文）。

## 领域列表

| id | 文件 | 触发示例 |
| --- | --- | --- |
| `software` | `software.md` | GitHub、API、SDK、版本、migration |
| `health_fitness` | `health_fitness.md` | 伤病、训练、营养、医学 |
| `vehicle_safety` | `vehicle_safety.md` | 碰撞、IIHS、NHTSA |
| `financial_safety` | `financial_safety.md` | 投资、贷款、保险 |
| `niche_contested` | `niche_contested.md` | 小众、争议、反例 |
| `time_sensitive` | `time_sensitive.md` | 最新、当前、今天 |
| `entity_research` | `entity_research.md` | 是谁、履历、获奖 |
| `official_docs` | `official_docs.md` | 官方文档、API reference |

## 如何增删领域

1. 新增 `src/grok_search/prompt_domains/<id>.md`（标题建议 `# Domain Addendum: <id>`）。  
2. 在 `prompt_domains/__init__.py` 的 `_DOMAIN_META` 登记 id、标题、简介、触发词。  
3. 补测试：`tests/test_search_quality.py`。  
4. 保持每个领域文件短小（建议 &lt; 2KB），不要把证据法条整段塞回 Grok。

客户端侧证据标准仍在 [CLIENT_SYSTEM_PROMPT.md](./CLIENT_SYSTEM_PROMPT.md)（层 A）。
