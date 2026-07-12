from typing import Any, Literal

from pydantic import BaseModel, Field


class Source(BaseModel):
    url: str
    title: str | None = None
    description: str | None = None
    provider: str | None = None


ResponseStatus = Literal["success", "partial_success", "error"]


class ErrorDetail(BaseModel):
    code: str
    message: str
    service: str
    retryable: bool
    http_status: int | None = None
    upstream_code: str | None = None
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class ResponseEnvelope(BaseModel):
    status: ResponseStatus = "success"
    error: str | None = None
    error_detail: ErrorDetail | None = None
    partial: bool = False


class TavilyErrorDetail(BaseModel):
    code: str
    message: str
    component: Literal["tavily"] = "tavily"
    retryable: bool = False
    http_status: int | None = None
    upstream_code: str | None = None
    key_statuses: list[dict[str, Any]] = Field(default_factory=list)
    service: dict[str, Any] = Field(default_factory=dict)
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class GrokErrorDetail(BaseModel):
    code: str
    message: str
    service: Literal["grok"] = "grok"
    retryable: bool = False
    primary_model: str
    fallback_model: str | None = None
    primary_attempts: int = Field(ge=0)
    fallback_attempts: int = Field(ge=0)
    total_attempts: int = Field(ge=0)
    last_error_type: str
    last_http_status: int | None = None
    last_upstream_code: str | None = None
    switched_model: bool = False
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class WebSearchResponse(ResponseEnvelope):
    session_id: str
    content: str
    sources_count: int = Field(ge=0)
    grok_error: GrokErrorDetail | None = None
    tavily_error: TavilyErrorDetail | None = None


class SourcesResponse(ResponseEnvelope):
    session_id: str
    sources: list[Source]
    sources_count: int = Field(ge=0)


class WebFetchResponse(ResponseEnvelope):
    url: str
    content: str = ""
    provider: Literal["tavily"] | None = None
    tavily_error: TavilyErrorDetail | None = None


class TavilySearchResult(BaseModel):
    title: str = ""
    url: str = ""
    content: str = ""
    score: float = 0


class TavilyMapResult(BaseModel):
    base_url: str = ""
    results: list[str] = Field(default_factory=list)
    response_time: float = 0
    ignored_results: int = Field(default=0, ge=0)


class WebMapResponse(TavilyMapResult, ResponseEnvelope):
    tavily_error: TavilyErrorDetail | None = None


class ConnectionTest(BaseModel):
    status: str
    message: str = ""
    response_time_ms: float = 0
    available_models: list[str] = Field(default_factory=list)
    error_detail: ErrorDetail | None = None


class ConfigInfoResponse(ResponseEnvelope):
    configuration: dict[str, Any] = Field(default_factory=dict)
    connection_test: ConnectionTest = Field(default_factory=lambda: ConnectionTest(status="未测试"))


class ModelSwitchResponse(ResponseEnvelope):
    success: bool
    previous_model: str | None = None
    current_model: str | None = None
    message: str
    config_file: str | None = None


class PlanningResponse(ResponseEnvelope):
    session_id: str = ""
    completed_phases: list[str] = Field(default_factory=list)
    complexity_level: int | None = None
    plan_complete: bool = False
    phases_remaining: list[str] = Field(default_factory=list)
    executable_plan: dict[str, Any] | None = None
