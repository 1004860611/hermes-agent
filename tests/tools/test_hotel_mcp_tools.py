import tools.hotel_mcp_tools  # noqa: F401
from tools.registry import registry
from toolsets import resolve_toolset


def test_hotel_mcp_tools_register_individual_toolsets():
    expected = {
        "order_search": "order_search",
        "order_bi_query": "order_bi_query",
        "hotelux_support_playbook": "hotelux_support_playbook",
        "order_points": "order_points",
        "order_confirmation": "order_confirmation",
        "points_reconcile": "points_reconcile",
        "order_benefits": "order_benefits",
        "cancellation_eligibility": "cancellation_eligibility",
        "payment_diagnosis": "payment_diagnosis",
        "change_precheck": "change_precheck",
        "hotelux_hotel_policy": "hotelux_hotel_policy",
        "charmdeer_support_playbook": "charmdeer_support_playbook",
        "charmdeer_hotel_policy": "charmdeer_hotel_policy",
        "coupon_status": "coupon_status",
        "promotion_explain": "promotion_explain",
        "member_entitlement": "member_entitlement",
        "afternoon_tea_status": "afternoon_tea_status",
        "points_balance": "points_balance",
        "case_precheck": "case_precheck",
        "case_handoff": "case_handoff",
        "activity_result_search": "activity_result_search",
        "activity_result_count": "activity_result_count",
        "resolver_time": "resolver_time",
        "resolver_city": "resolver_city",
        "resolver_country": "resolver_country",
        "resolver_hotel": "resolver_hotel",
        "resolver_channel": "resolver_channel",
        "resolver_payment_type": "resolver_payment_type",
        "resolver_shop_brand": "resolver_shop_brand",
        "resolver_shop_group": "resolver_shop_group",
    }

    for tool_name, toolset in expected.items():
        entry = registry.get_entry(tool_name)
        assert entry is not None
        assert entry.toolset == toolset
        assert resolve_toolset(toolset) == [tool_name]


def test_hotel_mcp_tool_schema_uses_public_snake_case_names():
    assert registry.get_entry("order_bi_query").schema["name"] == "order_bi_query"
    assert registry.get_entry("resolver_payment_type").schema["name"] == "resolver_payment_type"
    assert registry.get_entry("resolver_shop_brand").schema["name"] == "resolver_shop_brand"
    assert registry.get_entry("resolver_shop_group").schema["name"] == "resolver_shop_group"
    assert registry.get_entry("afternoon_tea_status").schema["name"] == "afternoon_tea_status"
    assert registry.get_entry("activity_result_search").schema["name"] == "activity_result_search"
