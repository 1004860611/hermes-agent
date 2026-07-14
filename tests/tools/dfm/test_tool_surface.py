import json

from hermes_constants import reset_hermes_home_override, set_hermes_home_override


def test_dfm_tools_are_discovered_with_stable_schemas_and_dispatch(tmp_path):
    from tools.registry import discover_builtin_tools, registry

    discover_builtin_tools()
    assert registry.get_tool_names_for_toolset("dfm") == ["dfm_analysis", "dfm_project"]
    project_schema = registry.get_schema("dfm_project")
    analysis_schema = registry.get_schema("dfm_analysis")
    assert project_schema["parameters"]["properties"]["action"]["enum"] == [
        "create", "add_input", "status", "confirm_fact", "list"
    ]
    assert analysis_schema["parameters"]["properties"]["action"]["enum"] == [
        "plan", "start", "status", "cancel", "result"
    ]

    token = set_hermes_home_override(tmp_path / "home")
    try:
        result = json.loads(registry.dispatch("dfm_project", {"action": "create", "name": "Bracket"}))
    finally:
        reset_hermes_home_override(token)
    assert result["ok"] is True


def test_dfm_toolset_is_default_off_but_explicitly_configurable():
    from hermes_cli.tools_config import CONFIGURABLE_TOOLSETS, _DEFAULT_OFF_TOOLSETS, _get_platform_tools
    from toolsets import resolve_toolset

    assert "dfm" in {item[0] for item in CONFIGURABLE_TOOLSETS}
    assert "dfm" in _DEFAULT_OFF_TOOLSETS
    assert "dfm" not in _get_platform_tools({}, "cli", include_default_mcp_servers=False)
    enabled = _get_platform_tools(
        {"platform_toolsets": {"cli": ["dfm"]}},
        "cli",
        include_default_mcp_servers=False,
    )
    assert "dfm" in enabled
    assert set(resolve_toolset("dfm")) == {"dfm_project", "dfm_analysis"}


def test_dfm_is_not_part_of_core_platform_tools():
    from toolsets import _HERMES_CORE_TOOLS

    assert "dfm_project" not in _HERMES_CORE_TOOLS
    assert "dfm_analysis" not in _HERMES_CORE_TOOLS
