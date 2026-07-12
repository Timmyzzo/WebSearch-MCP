from typing import Any, Literal

from pydantic import BaseModel, Field


class Source(BaseModel):
    url: str
    title: str | None = None
    description: str | None = None
    provider: str | None = None


class TavilyErrorDetail(BaseModel):
    code: str
    message: str
    key_statuses: list[dict[str, Any]] = Field(default_factory=list)
    service: dict[str, Any] = Field(default_factory=dict)


class GrokErrorDetail(BaseModel):
    code: str
    message: str
    primary_model: str
    fallback_model: str | None = None
    primary_attempts: int = Field(ge=0)
    fallback_attempts: int = Field(ge=0)
    total_attempts: int = Field(ge=0)
    last_error_type: str
    last_http_status: int | None = None
    last_upstream_code: str | None = None
    switched_model: bool = False


class WebSearchResponse(BaseModel):
    session_id: str
    content: str
    sources_count: int = Field(ge=0)
    error: str | None = None
    partial: bool = False
    grok_error: GrokErrorDetail | None = None
    tavily_error: TavilyErrorDetail | None = None


class SourcesResponse(BaseModel):
    session_id: str
    sources: list[Source]
    sources_count: int = Field(ge=0)
    error: str | None = None


class WebFetchResponse(BaseModel):
    url: str
    content: str = ""
    provider: Literal["tavily"] | None = None
    error: str | None = None
    tavily_error: TavilyErrorDetail | None = None


class TavilySearchResult(BaseModel):
    title: str = ""
    url: str = ""
    content: str = ""
    score: float = 0


class TavilyMapResult(BaseModel):
    base_url: str = ""
    results: list[Any] = Field(default_factory=list)
    response_time: float = 0


class WebMapResponse(TavilyMapResult):
    error: str | None = None
    tavily_error: TavilyErrorDetail | None = None


class ConnectionTest(BaseModel):
    status: str
    message: str = ""
    response_time_ms: float = 0
    available_models: list[str] = Field(default_factory=list)


class ConfigInfoResponse(BaseModel):
    configuration: dict[str, Any]
    connection_test: ConnectionTest


class ModelSwitchResponse(BaseModel):
    success: bool
    previous_model: str | None = None
    current_model: str | None = None
    message: str
    config_file: str | None = None
