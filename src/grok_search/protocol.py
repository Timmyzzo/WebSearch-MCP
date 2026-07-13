import re
from typing import Any

from .models import ErrorDetail, GrokErrorDetail, TavilyErrorDetail

_BEARER_PATTERN = re.compile(r"(?i)authorization\s*:\s*bearer\s+[^\s,;]+|bearer\s+[^\s,;]+")
_CREDENTIAL_PATTERN = re.compile(
    r"(?i)(api[_ -]?key|access[_ -]?token|authorization|credential|password|secret)"
    r"(\s*[:=]\s*)([^\s,;]+)"
)


def sanitize_diagnostic_text(
    value: object,
    *,
    secrets: tuple[str, ...] = (),
    limit: int = 200,
) -> str:
    text = str(value)
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[REDACTED]")
    text = _BEARER_PATTERN.sub("[REDACTED]", text)
    text = _CREDENTIAL_PATTERN.sub("[REDACTED]", text)
    text = " ".join(text.split())
    return text[:limit]


def make_error_detail(
    *,
    code: str,
    message: str,
    service: str,
    retryable: bool,
    http_status: int | None = None,
    upstream_code: str | None = None,
    diagnostics: dict[str, Any] | None = None,
) -> ErrorDetail:
    return ErrorDetail(
        code=code,
        message=message,
        service=service,
        retryable=retryable,
        http_status=http_status,
        upstream_code=upstream_code,
        diagnostics=diagnostics or {},
    )


def error_from_grok(detail: GrokErrorDetail) -> ErrorDetail:
    diagnostics: dict[str, Any] = {
        "primary_model": detail.primary_model,
        "fallback_model": detail.fallback_model,
        "primary_attempts": detail.primary_attempts,
        "fallback_attempts": detail.fallback_attempts,
        "total_attempts": detail.total_attempts,
        "last_error_type": detail.last_error_type,
        "switched_model": detail.switched_model,
        "termination_reason": detail.termination_reason,
        "configured_max_attempts": detail.configured_max_attempts,
        "actual_attempts": detail.actual_attempts,
        "elapsed_ms": detail.elapsed_ms,
        "budget_ms": detail.budget_ms,
        "queue_wait_ms": detail.queue_wait_ms,
    }
    diagnostics.update(detail.diagnostics)
    return make_error_detail(
        code=detail.code,
        message=detail.message,
        service="grok",
        retryable=detail.retryable,
        http_status=detail.last_http_status,
        upstream_code=detail.last_upstream_code,
        diagnostics=diagnostics,
    )


def error_from_tavily(detail: TavilyErrorDetail) -> ErrorDetail:
    diagnostics: dict[str, Any] = {}
    if detail.key_statuses:
        diagnostics["key_statuses"] = detail.key_statuses
    if detail.service:
        diagnostics["service_circuit"] = detail.service
    diagnostics.update(detail.diagnostics)
    return make_error_detail(
        code=detail.code,
        message=detail.message,
        service="tavily",
        retryable=detail.retryable,
        http_status=detail.http_status,
        upstream_code=detail.upstream_code,
        diagnostics=diagnostics,
    )


def internal_error_detail(service: str, exc: BaseException) -> ErrorDetail:
    return make_error_detail(
        code=f"{service}_internal_error",
        message=f"{service} 组件发生内部错误，当前工具调用已停止",
        service=service,
        retryable=False,
        diagnostics={"exception_type": type(exc).__name__},
    )
