from typing import Any, Literal

from pydantic import BaseModel, Field


class Source(BaseModel):
    url: str
    title: str | None = None
    description: str | None = None
    provider: str | None = None


class WebSearchResponse(BaseModel):
    session_id: str
    content: str
    sources_count: int = Field(ge=0)
    error: str | None = None


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
