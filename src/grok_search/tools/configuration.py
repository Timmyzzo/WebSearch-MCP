import time
from typing import Annotated

import httpx
from pydantic import Field

from ..app import mcp
from ..clients import GrokClientError
from ..config import config
from ..models import ConfigInfoResponse, ConnectionTest, ModelSwitchResponse
from ..protocol import make_error_detail, sanitize_diagnostic_text


def _redact_error_text(value: object, api_key: str) -> str:
    return sanitize_diagnostic_text(value, secrets=(api_key,))


@mcp.tool(
    name="get_config_info",
    description="Return masked configuration and test Grok API connectivity.",
    meta={"version": "2.0.0"},
)
async def get_config_info() -> ConfigInfoResponse:
    try:
        configuration = config.get_config_info()
    except Exception as exc:
        detail = make_error_detail(
            code="configuration_internal_error",
            message="无法读取脱敏配置信息",
            service="configuration",
            retryable=False,
            diagnostics={"exception_type": type(exc).__name__},
        )
        return ConfigInfoResponse(
            status="error",
            error=detail.code,
            error_detail=detail,
        )
    test = ConnectionTest(status="未测试")
    config_status = str(configuration.get("config_status", ""))
    detail = (
        make_error_detail(
            code="grok_configuration_error",
            message=sanitize_diagnostic_text(config_status),
            service="grok",
            retryable=False,
            diagnostics={"configuration": "grok"},
        )
        if config_status.startswith("❌")
        else None
    )
    api_key = ""
    try:
        api_url = config.grok_api_url
        api_key = config.grok_api_key
        started = time.perf_counter()
        from .web import _get_grok_client

        models = await (await _get_grok_client(api_url, api_key)).list_models()
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        test = ConnectionTest(
            status="连接成功",
            message=f"成功获取模型列表，共 {len(models)} 个模型",
            response_time_ms=elapsed_ms,
            available_models=models,
        )
    except httpx.TimeoutException:
        detail = make_error_detail(
            code="grok_connection_timeout",
            message="Grok 连接测试超时，请检查网络连接或 API URL",
            service="grok",
            retryable=True,
        )
        test = ConnectionTest(
            status="连接超时",
            message="请求超时（10秒），请检查网络连接或 API URL",
            error_detail=detail,
        )
    except httpx.RequestError as exc:
        detail = make_error_detail(
            code="grok_connection_error",
            message="无法连接 Grok API",
            service="grok",
            retryable=True,
            diagnostics={"exception_type": type(exc).__name__},
        )
        test = ConnectionTest(
            status="连接失败",
            message=f"网络错误: {type(exc).__name__}",
            error_detail=detail,
        )
    except ValueError as exc:
        detail = make_error_detail(
            code="grok_configuration_error",
            message=_redact_error_text(exc, api_key),
            service="grok",
            retryable=False,
            diagnostics={"configuration": "grok"},
        )
        test = ConnectionTest(status="配置错误", message=detail.message, error_detail=detail)
    except GrokClientError as exc:
        detail = make_error_detail(
            code=exc.code,
            message=exc.message,
            service="grok",
            retryable=exc.retryable,
            http_status=exc.last_http_status,
            upstream_code=exc.last_upstream_code,
            diagnostics={"total_attempts": exc.total_attempts},
        )
        test = ConnectionTest(
            status="连接异常",
            message=exc.message,
            error_detail=detail,
        )
    except Exception as exc:
        error_type = getattr(exc, "error_type", "")
        http_status = getattr(exc, "http_status", None)
        upstream_code = getattr(exc, "upstream_code", None)
        if error_type:
            code = (
                "grok_authentication_error"
                if error_type == "authentication_error"
                else "grok_model_catalog_error"
            )
            retryable = getattr(exc, "action", "fatal") in {"retry", "switch"}
        else:
            code = "grok_connection_test_error"
            retryable = False
        detail = make_error_detail(
            code=code,
            message="Grok 连接测试失败",
            service="grok",
            retryable=retryable,
            http_status=http_status,
            upstream_code=upstream_code,
            diagnostics={"exception_type": type(exc).__name__},
        )
        test = ConnectionTest(
            status="测试失败",
            message=f"连接测试失败: {type(exc).__name__}",
            error_detail=detail,
        )
    return ConfigInfoResponse(
        status="partial_success" if detail else "success",
        partial=detail is not None,
        error=detail.code if detail else None,
        error_detail=detail,
        configuration=configuration,
        connection_test=test,
    )


@mcp.tool(
    name="switch_model",
    description="Persist the primary Grok model used by subsequent searches.",
    meta={"version": "2.0.0"},
)
async def switch_model(
    model: Annotated[str, Field(description="Grok model ID to persist.", min_length=1)],
) -> ModelSwitchResponse:
    try:
        previous_model = config.grok_primary_model
        config.set_model(model)
        return ModelSwitchResponse(
            status="success",
            success=True,
            previous_model=previous_model,
            current_model=config.grok_primary_model,
            message=f"主模型已从 {previous_model} 切换到 {config.grok_primary_model}",
            config_file=str(config.config_file),
        )
    except Exception as exc:
        message = "切换模型失败，主模型未更改"
        detail = make_error_detail(
            code="model_switch_failed",
            message=message,
            service="configuration",
            retryable=False,
            diagnostics={"exception_type": type(exc).__name__},
        )
        return ModelSwitchResponse(
            status="error",
            success=False,
            message=message,
            error=message,
            error_detail=detail,
        )
