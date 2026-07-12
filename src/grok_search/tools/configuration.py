import re
import time
from typing import Annotated

import httpx
from pydantic import Field

from ..app import mcp
from ..clients import GrokClientError
from ..config import config
from ..models import ConfigInfoResponse, ConnectionTest, ModelSwitchResponse


def _redact_error_text(value: object, api_key: str) -> str:
    message = str(value).replace(api_key, "[REDACTED]") if api_key else str(value)
    return re.sub(r"(?i)bearer\s+[a-z0-9._~+/=-]+", "Bearer [REDACTED]", message)[:200]


@mcp.tool(
    name="get_config_info",
    description="Return masked configuration and test Grok API connectivity.",
    meta={"version": "1.4.0"},
)
async def get_config_info() -> ConfigInfoResponse:
    configuration = config.get_config_info()
    test = ConnectionTest(status="未测试")
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
        test = ConnectionTest(
            status="连接超时", message="请求超时（10秒），请检查网络连接或 API URL"
        )
    except httpx.RequestError as exc:
        test = ConnectionTest(
            status="连接失败", message=f"网络错误: {_redact_error_text(exc, api_key)}"
        )
    except ValueError as exc:
        test = ConnectionTest(status="配置错误", message=str(exc))
    except GrokClientError as exc:
        test = ConnectionTest(
            status="连接异常",
            message=exc.message,
        )
    except Exception as exc:
        test = ConnectionTest(
            status="测试失败", message=f"未知错误: {_redact_error_text(exc, api_key)}"
        )
    return ConfigInfoResponse(configuration=configuration, connection_test=test)


@mcp.tool(
    name="switch_model",
    description="Persist the primary Grok model used by subsequent searches.",
    meta={"version": "1.5.0"},
)
async def switch_model(
    model: Annotated[str, Field(description="Grok model ID to persist.", min_length=1)],
) -> ModelSwitchResponse:
    try:
        previous_model = config.grok_primary_model
        config.set_model(model)
        return ModelSwitchResponse(
            success=True,
            previous_model=previous_model,
            current_model=config.grok_primary_model,
            message=f"主模型已从 {previous_model} 切换到 {config.grok_primary_model}",
            config_file=str(config.config_file),
        )
    except Exception as exc:
        return ModelSwitchResponse(success=False, message=f"切换模型失败: {exc}")
