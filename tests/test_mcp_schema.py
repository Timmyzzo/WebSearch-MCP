from grok_search import mcp


async def test_tool_schemas_are_cross_client_safe():
    tools = {tool.name: tool for tool in await mcp.list_tools()}
    core_tools = {
        "web_search",
        "get_sources",
        "web_fetch",
        "web_map",
        "get_config_info",
        "switch_model",
    }

    assert core_tools.issubset(tools)
    assert "toggle_builtin_tools" not in tools
    for tool in tools.values():
        assert tool.parameters.get("additionalProperties") is False
        assert tool.output_schema is not None
        assert "ctx" not in tool.parameters.get("properties", {})
        output = tool.output_schema["properties"]
        assert output["status"]["enum"] == ["success", "partial_success", "error"]
        error_object = output["error_detail"]["anyOf"][0]
        assert error_object["required"] == ["code", "message", "service", "retryable"]

    assert tools["web_search"].parameters["required"] == ["query"]
    assert tools["web_fetch"].parameters["required"] == ["url"]
    assert tools["web_map"].output_schema["properties"]["results"]["items"] == {
        "type": "string"
    }
    for name in tools:
        if name.startswith("plan_"):
            assert "thought" not in tools[name].parameters.get("required", [])
