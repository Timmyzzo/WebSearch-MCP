"""On-demand domain addenda for Layer-B Grok search prompts.

Each domain is a short Markdown file. The base system prompt only catalogs
domain keys; matching addenda are appended at request time so simple queries
stay light.
"""

from __future__ import annotations

import re
from functools import lru_cache
from importlib import resources
from pathlib import Path

# id -> (title, short catalog line for base prompt, trigger terms)
_DOMAIN_META: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "software": (
        "Software / GitHub / APIs",
        "libraries, APIs, SDKs, GitHub, packages, releases, migrations, bugs",
        (
            "github",
            "gitlab",
            "api",
            "sdk",
            "依赖",
            "软件",
            "代码",
            "报错",
            "错误",
            "迁移",
            "版本",
            "release",
            "changelog",
            "commit",
            "issue",
            "pull request",
            "library",
            "framework",
            "package",
            "repository",
            "bug",
            "deprecated",
        ),
    ),
    "health_fitness": (
        "Health / fitness / nutrition",
        "medical, injury, diet, training, recovery, sports performance",
        (
            "健康",
            "疾病",
            "药物",
            "伤病",
            "疼痛",
            "营养",
            "饮食",
            "训练",
            "健身",
            "运动表现",
            "恢复",
            "减脂",
            "增肌",
            "health",
            "medical",
            "medicine",
            "injury",
            "pain",
            "nutrition",
            "diet",
            "training",
            "fitness",
            "recovery",
        ),
    ),
    "vehicle_safety": (
        "Vehicle / crash safety",
        "collision tests, IIHS/NHTSA/Euro NCAP ratings",
        (
            "汽车安全",
            "碰撞",
            "车祸",
            "车型安全",
            "安全座椅",
            "iihs",
            "nhtsa",
            "euro ncap",
            "ancap",
            "crash test",
            "vehicle safety",
        ),
    ),
    "financial_safety": (
        "Financial safety",
        "investing, loans, insurance, personal finance risk",
        (
            "投资建议",
            "理财",
            "贷款",
            "保险",
            "财务安全",
            "financial advice",
            "investment",
            "loan",
            "insurance",
        ),
    ),
    "niche_contested": (
        "Niche / contested topics",
        "counterexamples, limitations, opposing schools, sparse evidence",
        (
            "小众",
            "冷门",
            "资料很少",
            "模糊",
            "突发奇想",
            "niche",
            "obscure",
            "little evidence",
            "hard to find",
            "争议",
            "反例",
            "局限",
            "限制条件",
            "不同观点",
            "不同学派",
            "是否真的",
            "controvers",
            "counterexample",
            "limitation",
            "opposing view",
            "schools of thought",
        ),
    ),
    "time_sensitive": (
        "Time-sensitive / latest",
        "latest, current, today, still supported, current version",
        (
            "最新",
            "当前",
            "今天",
            "最近",
            "现版本",
            "最新版",
            "最新发布",
            "仍然支持",
            "当前默认",
            "latest",
            "current",
            "today",
            "recent",
            "now",
            "still supported",
            "default behavior",
        ),
    ),
    "entity_research": (
        "Entity / public records",
        "who is, biography, awards, competition records",
        (
            "是谁",
            "什么人",
            "背景",
            "履历",
            "获奖",
            "奖项",
            "参赛记录",
            "竞赛记录",
            "公开记录",
            "who is",
            "background",
            "biography",
            "profile",
            "awards",
            "competition record",
            "public record",
        ),
    ),
    "official_docs": (
        "Official documentation",
        "official docs, API reference, standards text",
        (
            "官方文档",
            "官方 readme",
            "api reference",
            "规范",
            "标准原文",
            "official documentation",
            "official docs",
            "official readme",
        ),
    ),
}

# Stable order for catalog and matching priority
DOMAIN_IDS: tuple[str, ...] = tuple(_DOMAIN_META.keys())
MAX_DOMAIN_ADDENDA = 3


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    for term in terms:
        if term.isascii() and term.isalnum():
            if re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text):
                return True
        elif term in text:
            return True
    return False


def match_domain_ids(query: str, *, limit: int = MAX_DOMAIN_ADDENDA) -> list[str]:
    """Return domain ids whose trigger terms match the query (capped)."""
    text = f" {query.casefold().strip()} "
    matched: list[str] = []
    for domain_id in DOMAIN_IDS:
        _, _, terms = _DOMAIN_META[domain_id]
        if _contains_any(text, terms):
            matched.append(domain_id)
            if len(matched) >= limit:
                break
    return matched


def domain_catalog_markdown() -> str:
    """Short catalog lines embedded in the base system prompt."""
    lines = [
        "## Domain addenda (on-demand)",
        "If the query matches a domain below, apply the corresponding Domain",
        "Addendum when it is appended after this base prompt (also listed in",
        "`active_domains` in the user JSON). If none match, use only this base",
        "prompt — do not invent domain rules.",
        "",
        "Available domains:",
    ]
    for domain_id in DOMAIN_IDS:
        title, blurb, _ = _DOMAIN_META[domain_id]
        lines.append(f"- `{domain_id}` — {title}: {blurb}")
    return "\n".join(lines)


def _domain_file_path(domain_id: str) -> Path:
    return Path(__file__).resolve().parent / f"{domain_id}.md"


@lru_cache(maxsize=32)
def load_domain_addendum(domain_id: str) -> str:
    """Load one domain Markdown addendum (cached)."""
    if domain_id not in _DOMAIN_META:
        raise KeyError(f"Unknown domain addendum: {domain_id}")
    path = _domain_file_path(domain_id)
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    # Fallback for zip/importlib package installs
    package = resources.files(__package__)
    return package.joinpath(f"{domain_id}.md").read_text(encoding="utf-8").strip()


def build_domain_addenda_block(domain_ids: list[str]) -> str:
    if not domain_ids:
        return ""
    parts = [
        "## Active domain addenda",
        "Apply the following domain-specific rules in addition to the base prompt.",
        f"Active domains: {', '.join(f'`{d}`' for d in domain_ids)}",
    ]
    for domain_id in domain_ids:
        parts.append("")
        parts.append(load_domain_addendum(domain_id))
    return "\n".join(parts).strip()


def clear_domain_cache() -> None:
    load_domain_addendum.cache_clear()
