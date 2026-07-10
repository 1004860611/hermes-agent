"""Hotel search tool backed by the Charmdeer hotel server callback API."""

from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timedelta
from typing import Any, Dict

from tools.enterprise_context import get_enterprise_context
from tools.hotel_mcp_client import call_consumer_mcp_tool
from tools.registry import registry


logger = logging.getLogger(__name__)


HOTEL_SEARCH_SCHEMA = {
    "name": "hotel_search",
    "description": (
        "Search live hotel availability and rates through the hotel system. "
        "Use this for destination, exact hotel, date range, stay nights, DBS, "
        "budget, currency, and guest-count hotel search requests."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "destination": {
                "type": "string",
                "description": "Destination city, such as Shanghai, Tokyo, Singapore.",
            },
            "hotelName": {
                "type": "string",
                "description": "Fuzzy hotel name search, such as Marriott or Park Hyatt.",
            },
            "searchRangeStart": {
                "type": "string",
                "description": "Flexible search start date, YYYY-MM-DD.",
            },
            "searchRangeEnd": {
                "type": "string",
                "description": "Flexible search end date, YYYY-MM-DD.",
            },
            "dateRangeStart": {
                "type": "string",
                "description": "Exact check-in date, YYYY-MM-DD.",
            },
            "dateRangeEnd": {
                "type": "string",
                "description": "Exact check-out date, YYYY-MM-DD.",
            },
            "stayNights": {
                "type": "number",
                "minimum": 1,
                "description": "Number of stay nights.",
            },
            "maxPrice": {
                "type": "number",
                "minimum": 1,
                "description": "Maximum total/tax-inclusive price.",
            },
            "currency": {
                "type": "string",
                "description": "Currency code, such as SGD, CNY, USD.",
            },
            "guestCount": {
                "type": "number",
                "minimum": 1,
                "maximum": 8,
                "description": "Number of adult guests. Defaults to 2.",
            },
            "isDBS": {
                "type": "boolean",
                "description": "Whether to search only DBS-designated hotels.",
            },
            "cityRef": {
                "type": "string",
                "description": "Resolved hotel system city ObjectId. Prefer passing this after resolver_city when available.",
            },
            "moduleTpHotelRef": {
                "type": "string",
                "description": "Resolved hotel system hotel ObjectId. Prefer passing this after resolver_hotel when available.",
            },
        },
    },
}


def _hotel_api_base_url() -> str:
    return os.getenv("HERMES_HOTEL_API_BASE_URL", "http://127.0.0.1:30001").rstrip("/")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default


def _hotel_timeout_seconds() -> float:
    requested = _env_float("HERMES_HOTEL_API_TIMEOUT_SECONDS", 120.0)
    cap = _env_float("HERMES_HOTEL_API_MAX_TIMEOUT_SECONDS", 120.0)
    if requested <= 0:
        requested = 45.0
    if cap <= 0:
        return requested
    return min(requested, cap)


def _extract_result(data: Dict[str, Any]) -> Dict[str, Any]:
    if "hermesTool" in data:
        return data["hermesTool"]
    return data


def _string_set(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        text = value.strip()
        return {text} if text else set()
    if isinstance(value, (list, tuple, set)):
        return {str(item).strip() for item in value if str(item or "").strip()}
    text = str(value).strip()
    return {text} if text else set()


def _tool_error(
    *,
    kind: str,
    code: str,
    message: str,
    user_message: str,
    recoverable: bool = True,
    missing_fields: list[str] | None = None,
    model_guidance: str = "",
    next_actions: list[str] | None = None,
) -> str:
    return json.dumps({
        "ok": False,
        "kind": kind,
        "recoverable": recoverable,
        "error": {
            "code": code,
            "message": message,
            "missingFields": list(missing_fields or []),
            "userMessage": user_message,
            "modelGuidance": model_guidance,
            "nextActions": list(next_actions or []),
        },
    }, ensure_ascii=False)


def _has_date_range(args: Dict[str, Any]) -> bool:
    search_start = str((args or {}).get("searchRangeStart") or "").strip()
    search_end = str((args or {}).get("searchRangeEnd") or "").strip()
    exact_start = str((args or {}).get("dateRangeStart") or "").strip()
    exact_end = str((args or {}).get("dateRangeEnd") or "").strip()
    return bool((search_start and search_end) or (exact_start and exact_end))


def _parse_date(value: Any, field: str) -> tuple[date | None, str | None]:
    text = str(value or "").strip()
    if not text:
        return None, f"Missing {field}."
    try:
        return datetime.strptime(text, "%Y-%m-%d").date(), None
    except ValueError:
        return None, f"{field} must use YYYY-MM-DD."


def _number(value: Any, field: str, *, integer: bool = False) -> tuple[float | int | None, str | None]:
    if value is None or value == "":
        return None, None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None, f"{field} must be a number."
    if parsed <= 0:
        return None, f"{field} must be greater than 0."
    if integer:
        if not parsed.is_integer():
            return None, f"{field} must be an integer."
        parsed = int(parsed)
    return parsed, None


def _clarification(
    *,
    code: str,
    message: str,
    user_message: str,
    missing_fields: list[str] | None = None,
    next_actions: list[str] | None = None,
) -> str:
    return _tool_error(
        kind="clarification_required",
        code=code,
        message=message,
        user_message=user_message,
        missing_fields=missing_fields,
        model_guidance=(
            "Ask the user only for the missing or narrowing information. "
            "Do not call hotel_search again until the search request is narrow enough."
        ),
        next_actions=next_actions or ["ask_user_to_narrow_hotel_search"],
    )


def _prepare_hotel_payload(args: Dict[str, Any]) -> tuple[Dict[str, Any] | None, str | None]:
    payload = dict(args or {})
    for key in ("destination", "hotelName", "currency"):
        if key in payload and payload[key] is not None:
            payload[key] = str(payload[key]).strip()

    destination = str(payload.get("destination") or "").strip()
    hotel_name = str(payload.get("hotelName") or "").strip()
    if not destination and not hotel_name:
        return None, _clarification(
            code="MISSING_SEARCH_TARGET",
            message="Missing hotel search destination or hotelName.",
            user_message="请补充要查询的目的地或酒店名称，例如“上海酒店”或“上海柏悦”。",
            missing_fields=["destination", "hotelName"],
            next_actions=["ask_user_for_destination_or_hotel_name"],
        )

    if not _has_date_range(payload):
        return None, _clarification(
            code="MISSING_REQUIRED_INFORMATION",
            message="Missing required hotel search date range.",
            user_message="我还需要入住日期和离店日期才能查询酒店。请补充类似“7月10日入住，7月12日离店”的信息。",
            missing_fields=["searchRangeStart", "searchRangeEnd", "dateRangeStart", "dateRangeEnd"],
            next_actions=["ask_user_for_date_range"],
        )

    search_start_text = str(payload.get("searchRangeStart") or "").strip()
    search_end_text = str(payload.get("searchRangeEnd") or "").strip()
    exact_start_text = str(payload.get("dateRangeStart") or "").strip()
    exact_end_text = str(payload.get("dateRangeEnd") or "").strip()

    if bool(search_start_text) != bool(search_end_text):
        missing = ["searchRangeEnd"] if search_start_text else ["searchRangeStart"]
        return None, _clarification(
            code="PARTIAL_DATE_RANGE",
            message="Flexible search range must include both searchRangeStart and searchRangeEnd.",
            user_message="请同时提供搜索开始日期和搜索结束日期。",
            missing_fields=missing,
        )
    if bool(exact_start_text) != bool(exact_end_text):
        missing = ["dateRangeEnd"] if exact_start_text else ["dateRangeStart"]
        return None, _clarification(
            code="PARTIAL_DATE_RANGE",
            message="Exact date range must include both dateRangeStart and dateRangeEnd.",
            user_message="请同时提供入住日期和离店日期。",
            missing_fields=missing,
        )

    stay_nights, error = _number(payload.get("stayNights"), "stayNights", integer=True)
    if error:
        return None, _clarification(
            code="INVALID_STAY_NIGHTS",
            message=error,
            user_message="入住晚数需要是大于 0 的数字。",
            missing_fields=["stayNights"],
        )

    max_stay_nights = _env_int("HERMES_HOTEL_MAX_STAY_NIGHTS", 14)
    if stay_nights and stay_nights > max_stay_nights:
        return None, _clarification(
            code="STAY_TOO_LONG",
            message=f"stayNights exceeds {max_stay_nights}.",
            user_message=f"当前最多支持一次查询 {max_stay_nights} 晚。请缩短入住晚数后再查。",
            missing_fields=["stayNights"],
        )

    today = date.today()
    if exact_start_text and exact_end_text:
        start, error = _parse_date(exact_start_text, "dateRangeStart")
        if error:
            return None, _clarification(
                code="INVALID_DATE_FORMAT",
                message=error,
                user_message="入住日期格式需要是 YYYY-MM-DD，例如 2026-07-10。",
                missing_fields=["dateRangeStart"],
            )
        end, error = _parse_date(exact_end_text, "dateRangeEnd")
        if error:
            return None, _clarification(
                code="INVALID_DATE_FORMAT",
                message=error,
                user_message="离店日期格式需要是 YYYY-MM-DD，例如 2026-07-12。",
                missing_fields=["dateRangeEnd"],
            )
        if end <= start:
            return None, _clarification(
                code="INVALID_DATE_ORDER",
                message="dateRangeEnd must be after dateRangeStart.",
                user_message="离店日期需要晚于入住日期。",
                missing_fields=["dateRangeEnd"],
            )
        if start < today:
            return None, _clarification(
                code="PAST_DATE_RANGE",
                message="dateRangeStart is in the past.",
                user_message="入住日期不能早于今天，请提供新的入住和离店日期。",
                missing_fields=["dateRangeStart"],
            )
        exact_nights = (end - start).days
        payload["stayNights"] = stay_nights or exact_nights
        if payload["stayNights"] > max_stay_nights:
            return None, _clarification(
                code="STAY_TOO_LONG",
                message=f"Exact stay exceeds {max_stay_nights} nights.",
                user_message=f"当前最多支持一次查询 {max_stay_nights} 晚。请缩短入住日期范围后再查。",
                missing_fields=["dateRangeStart", "dateRangeEnd"],
            )
        if stay_nights and stay_nights != exact_nights:
            payload["stayNights"] = exact_nights

    if search_start_text and search_end_text:
        start, error = _parse_date(search_start_text, "searchRangeStart")
        if error:
            return None, _clarification(
                code="INVALID_DATE_FORMAT",
                message=error,
                user_message="搜索开始日期格式需要是 YYYY-MM-DD，例如 2026-07-10。",
                missing_fields=["searchRangeStart"],
            )
        end, error = _parse_date(search_end_text, "searchRangeEnd")
        if error:
            return None, _clarification(
                code="INVALID_DATE_FORMAT",
                message=error,
                user_message="搜索结束日期格式需要是 YYYY-MM-DD，例如 2026-07-20。",
                missing_fields=["searchRangeEnd"],
            )
        if end < start:
            return None, _clarification(
                code="INVALID_DATE_ORDER",
                message="searchRangeEnd must be on or after searchRangeStart.",
                user_message="搜索结束日期不能早于搜索开始日期。",
                missing_fields=["searchRangeEnd"],
            )
        if start < today:
            return None, _clarification(
                code="PAST_DATE_RANGE",
                message="searchRangeStart is in the past.",
                user_message="搜索日期不能早于今天，请提供新的日期范围。",
                missing_fields=["searchRangeStart"],
            )
        window_days = (end - start).days + 1
        max_window_days = _env_int("HERMES_HOTEL_SEARCH_WINDOW_MAX_DAYS", 14)
        if window_days > max_window_days and not hotel_name:
            return None, _clarification(
                code="SEARCH_WINDOW_TOO_WIDE",
                message=f"Flexible hotel search window exceeds {max_window_days} days.",
                user_message=(
                    f"这个查询范围有 {window_days} 天，可能会很慢。请把日期范围缩小到 "
                    f"{max_window_days} 天以内，或补充具体酒店名称。"
                ),
                missing_fields=["searchRangeStart", "searchRangeEnd", "hotelName"],
            )
        if not stay_nights:
            return None, _clarification(
                code="MISSING_STAY_NIGHTS",
                message="Flexible hotel search requires stayNights.",
                user_message="请补充入住晚数，例如“住 2 晚”。",
                missing_fields=["stayNights"],
            )

    max_price, error = _number(payload.get("maxPrice"), "maxPrice")
    if error:
        return None, _clarification(
            code="INVALID_MAX_PRICE",
            message=error,
            user_message="价格上限需要是大于 0 的数字。",
            missing_fields=["maxPrice"],
        )
    if max_price is not None:
        payload["maxPrice"] = max_price

    guest_count, error = _number(payload.get("guestCount", 2), "guestCount", integer=True)
    if error:
        return None, _clarification(
            code="INVALID_GUEST_COUNT",
            message=error,
            user_message="入住人数需要是大于 0 的数字。",
            missing_fields=["guestCount"],
        )
    max_guest_count = _env_int("HERMES_HOTEL_MAX_GUEST_COUNT", 8)
    if guest_count and guest_count > max_guest_count:
        return None, _clarification(
            code="GUEST_COUNT_TOO_LARGE",
            message=f"guestCount exceeds {max_guest_count}.",
            user_message=f"当前最多支持一次查询 {max_guest_count} 位成人。请减少人数或拆分查询。",
            missing_fields=["guestCount"],
        )
    payload["guestCount"] = guest_count or 2

    return payload, None


def _hotel_search_mcp_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Translate Hermes' public hotel_search args to Charmdeer MCP hotel.search input."""
    payload = dict(payload or {})

    filter_obj = dict(payload.get("filter") or {})
    existing_criteria = filter_obj.get("_criteria")
    if existing_criteria is not None:
        filter_obj["_criteria"] = dict(existing_criteria) if isinstance(existing_criteria, dict) else existing_criteria

    hotel_ref = str(payload.get("moduleTpHotelRef") or payload.get("hotelRef") or "").strip()
    city_ref = str(payload.get("cityRef") or "").strip()
    hotel_name = str(payload.get("hotelName") or "").strip()
    destination = str(payload.get("destination") or "").strip()

    if hotel_ref:
        filter_obj.setdefault("hotels", [{"_id": hotel_ref}])
    elif hotel_name:
        filter_obj.setdefault("search", hotel_name)
    elif city_ref:
        filter_obj.setdefault("city", {"_id": city_ref})
    elif destination:
        # The hotel backend's search adapter accepts free-text search. A resolved
        # cityRef is still preferred, but this keeps legacy destination calls usable.
        filter_obj.setdefault("search", destination)

    if "upgradeToGold" not in filter_obj:
        filter_obj["upgradeToGold"] = bool(payload.get("isDBS")) if "isDBS" in payload else False

    check_in = str(payload.get("dateRangeStart") or "").strip()
    check_out = str(payload.get("dateRangeEnd") or "").strip()

    if not (check_in and check_out):
        search_start = str(payload.get("searchRangeStart") or "").strip()
        stay_nights = int(payload.get("stayNights") or 1)
        check_in = search_start
        try:
            check_out = (datetime.strptime(search_start, "%Y-%m-%d").date() + timedelta(days=stay_nights)).isoformat()
        except Exception:
            check_out = str(payload.get("searchRangeEnd") or "").strip()

    stay = dict(payload.get("stay") or {})
    stay_date = dict(stay.get("date") or {})
    stay_date.setdefault("checkIn", check_in)
    stay_date.setdefault("checkOut", check_out)
    stay["date"] = stay_date
    stay.setdefault("guest", {})
    if isinstance(stay["guest"], dict):
        stay["guest"].setdefault("numberOfAdults", int(payload.get("guestCount") or 2))
        stay["guest"].setdefault("numberOfChildren", 0)

    preferred = dict(payload.get("preferred") or {})
    currency = str(payload.get("currency") or "").strip()
    if currency:
        preferred.setdefault("currency", currency.upper())

    paging = dict(payload.get("paging") or {})
    paging.setdefault("skip", 0)
    paging.setdefault("limit", _env_int("HERMES_HOTEL_SEARCH_LIMIT", 10))

    mcp_payload = {
        "stay": stay,
        "filter": filter_obj,
        "paging": paging,
        "sort": payload.get("sort") or "byRecommendation",
        "preferred": preferred,
    }
    if payload.get("maxPrice") is not None:
        mcp_payload["maxPrice"] = payload["maxPrice"]
    return mcp_payload


async def _handle_hotel_search(args: Dict[str, Any], task_id: str = None, **_: Any) -> str:
    args = args or {}
    enterprise_context = get_enterprise_context(task_id)
    payload, validation_error = _prepare_hotel_payload(args)
    if validation_error:
        return validation_error

    allowed_capabilities = _string_set(enterprise_context.get("allowed_capabilities"))
    if allowed_capabilities and "hotel_search" not in allowed_capabilities:
        return _tool_error(
            kind="permission_denied",
            code="CAPABILITY_NOT_ALLOWED",
            message="hotel_search is not allowed for this enterprise turn.",
            user_message="当前会话没有酒店查询权限。",
            recoverable=False,
        )

    credential_scope = _string_set(enterprise_context.get("credential_scope"))
    if credential_scope and "hotel_search" not in credential_scope:
        return _tool_error(
            kind="permission_denied",
            code="CREDENTIAL_SCOPE_DENIED",
            message="The enterprise credentialRef is not scoped for hotel_search.",
            user_message="当前凭证不能用于酒店查询，请刷新页面或重新登录后再试。",
            recoverable=False,
        )

    credential_ref = enterprise_context.get("credentialRef")
    if not credential_ref:
        return _tool_error(
            kind="credential_required",
            code="CREDENTIAL_REQUIRED",
            message="Missing enterprise credentialRef for hotel_search.",
            user_message="当前酒店查询凭证缺失，请刷新页面或重新登录后再试。",
            recoverable=False,
        )

    return await call_consumer_mcp_tool(
        task_id=task_id,
        tool_name="hotel.search",
        capability_ref="hotel_search",
        payload=_hotel_search_mcp_payload(payload),
        user_tool_name="hotel_search",
    )


registry.register(
    name="hotel_search",
    toolset="hotel",
    schema=HOTEL_SEARCH_SCHEMA,
    handler=_handle_hotel_search,
    is_async=True,
    description=HOTEL_SEARCH_SCHEMA["description"],
    max_result_size_chars=120_000,
)
