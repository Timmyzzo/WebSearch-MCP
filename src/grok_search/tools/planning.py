import json
from typing import Annotated, Literal

from pydantic import Field

from ..app import mcp
from ..planning import _split_csv
from ..planning import engine as planning_engine


def _missing_session(session_id: str) -> dict[str, str] | None:
    if planning_engine.get_session(session_id):
        return None
    return {"error": f"Session '{session_id}' not found. Call plan_intent first."}


@mcp.tool(name="plan_intent", description="Optionally start or revise a structured search plan.")
async def plan_intent(
    core_question: Annotated[str, Field(description="Distilled core question.", min_length=1)],
    query_type: Annotated[
        Literal["factual", "comparative", "exploratory", "analytical"],
        Field(description="Question type."),
    ],
    time_sensitivity: Annotated[
        Literal["realtime", "recent", "historical", "irrelevant"],
        Field(description="How time-sensitive the answer is."),
    ],
    session_id: Annotated[str, Field(description="Existing session to revise, or empty.")] = "",
    confidence: Annotated[float, Field(description="Confidence score.", ge=0, le=1)] = 1.0,
    domain: Annotated[str, Field(description="Optional domain.")] = "",
    premise_valid: Annotated[
        bool | None, Field(description="Whether the premise is valid.")
    ] = None,
    ambiguities: Annotated[str, Field(description="Comma-separated ambiguities.")] = "",
    unverified_terms: Annotated[str, Field(description="Comma-separated terms to verify.")] = "",
    is_revision: Annotated[bool, Field(description="Overwrite the previous intent.")] = False,
    thought: Annotated[str, Field(description="Optional concise planning note.")] = "",
) -> dict:
    data: dict = {
        "core_question": core_question,
        "query_type": query_type,
        "time_sensitivity": time_sensitivity,
    }
    if domain:
        data["domain"] = domain
    if premise_valid is not None:
        data["premise_valid"] = premise_valid
    if ambiguities:
        data["ambiguities"] = _split_csv(ambiguities)
    if unverified_terms:
        data["unverified_terms"] = _split_csv(unverified_terms)
    return planning_engine.process_phase(
        phase="intent_analysis",
        thought=thought,
        session_id=session_id,
        is_revision=is_revision,
        confidence=confidence,
        phase_data=data,
    )


@mcp.tool(name="plan_complexity", description="Optionally assess search complexity from 1 to 3.")
async def plan_complexity(
    session_id: Annotated[str, Field(description="Session ID from plan_intent.", min_length=1)],
    level: Annotated[int, Field(description="Complexity level.", ge=1, le=3)],
    estimated_sub_queries: Annotated[int, Field(ge=1, le=20)],
    estimated_tool_calls: Annotated[int, Field(ge=1, le=50)],
    justification: Annotated[str, Field(min_length=1)],
    confidence: Annotated[float, Field(ge=0, le=1)] = 1.0,
    is_revision: bool = False,
    thought: str = "",
) -> dict:
    if missing := _missing_session(session_id):
        return missing
    return planning_engine.process_phase(
        phase="complexity_assessment",
        thought=thought,
        session_id=session_id,
        is_revision=is_revision,
        confidence=confidence,
        phase_data={
            "level": level,
            "estimated_sub_queries": estimated_sub_queries,
            "estimated_tool_calls": estimated_tool_calls,
            "justification": justification,
        },
    )


@mcp.tool(name="plan_sub_query", description="Optionally add one sub-query to a search plan.")
async def plan_sub_query(
    session_id: str,
    id: str,
    goal: str,
    expected_output: str,
    boundary: str,
    confidence: Annotated[float, Field(ge=0, le=1)] = 1.0,
    depends_on: str = "",
    tool_hint: Literal["web_search", "web_fetch", "web_map", ""] = "",
    is_revision: bool = False,
    thought: str = "",
) -> dict:
    if missing := _missing_session(session_id):
        return missing
    item: dict = {"id": id, "goal": goal, "expected_output": expected_output, "boundary": boundary}
    if depends_on:
        item["depends_on"] = _split_csv(depends_on)
    if tool_hint:
        item["tool_hint"] = tool_hint
    return planning_engine.process_phase(
        phase="query_decomposition",
        thought=thought,
        session_id=session_id,
        is_revision=is_revision,
        confidence=confidence,
        phase_data=item,
    )


@mcp.tool(name="plan_search_term", description="Optionally add one search term to a plan.")
async def plan_search_term(
    session_id: str,
    term: str,
    purpose: str,
    round: Annotated[int, Field(ge=1)],
    confidence: Annotated[float, Field(ge=0, le=1)] = 1.0,
    approach: Literal["broad_first", "narrow_first", "targeted", ""] = "",
    fallback_plan: str = "",
    is_revision: bool = False,
    thought: str = "",
) -> dict:
    if missing := _missing_session(session_id):
        return missing
    data: dict = {"search_terms": [{"term": term, "purpose": purpose, "round": round}]}
    if approach:
        data["approach"] = approach
    if fallback_plan:
        data["fallback_plan"] = fallback_plan
    return planning_engine.process_phase(
        phase="search_strategy",
        thought=thought,
        session_id=session_id,
        is_revision=is_revision,
        confidence=confidence,
        phase_data=data,
    )


@mcp.tool(name="plan_tool_mapping", description="Optionally map one sub-query to a web tool.")
async def plan_tool_mapping(
    session_id: str,
    sub_query_id: str,
    tool: Literal["web_search", "web_fetch", "web_map"],
    reason: str,
    confidence: Annotated[float, Field(ge=0, le=1)] = 1.0,
    params_json: str = "",
    is_revision: bool = False,
    thought: str = "",
) -> dict:
    if missing := _missing_session(session_id):
        return missing
    item: dict = {"sub_query_id": sub_query_id, "tool": tool, "reason": reason}
    if params_json:
        try:
            item["params"] = json.loads(params_json)
        except json.JSONDecodeError:
            item["params"] = {}
    return planning_engine.process_phase(
        phase="tool_selection",
        thought=thought,
        session_id=session_id,
        is_revision=is_revision,
        confidence=confidence,
        phase_data=item,
    )


@mcp.tool(name="plan_execution", description="Optionally define execution order for a search plan.")
async def plan_execution(
    session_id: str,
    parallel_groups: str,
    sequential: str,
    estimated_rounds: Annotated[int, Field(ge=1)],
    confidence: Annotated[float, Field(ge=0, le=1)] = 1.0,
    is_revision: bool = False,
    thought: str = "",
) -> dict:
    if missing := _missing_session(session_id):
        return missing
    parallel = [_split_csv(group) for group in parallel_groups.split(";") if group.strip()]
    return planning_engine.process_phase(
        phase="execution_order",
        thought=thought,
        session_id=session_id,
        is_revision=is_revision,
        confidence=confidence,
        phase_data={
            "parallel": parallel,
            "sequential": _split_csv(sequential),
            "estimated_rounds": estimated_rounds,
        },
    )
