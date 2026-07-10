"""Shared HTTP callback client for Charmdeer MCP-backed hotel tools."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict

from tools.enterprise_context import get_enterprise_context


logger = logging.getLogger(__name__)


def hotel_api_base_url() -> str:
    return os.getenv("HERMES_HOTEL_API_BASE_URL", "http://127.0.0.1:30001").rstrip("/")


def env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default


def hotel_timeout_seconds() -> float:
    requested = env_float("HERMES_HOTEL_API_TIMEOUT_SECONDS", 120.0)
    cap = env_float("HERMES_HOTEL_API_MAX_TIMEOUT_SECONDS", 120.0)
    if requested <= 0:
        requested = 45.0
    if cap <= 0:
        return requested
    return min(requested, cap)


def extract_hermes_tool_result(data: Dict[str, Any]) -> Any:
    if isinstance(data, dict) and "hermesTool" in data:
        return data["hermesTool"]
    return data


def string_set(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        text = value.strip()
        return {text} if text else set()
    if isinstance(value, (list, tuple, set)):
        return {str(item).strip() for item in value if str(item or "").strip()}
    text = str(value).strip()
    return {text} if text else set()


def tool_error(
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


def _scope_allows(scope: set[str], capability_ref: str, aliases: set[str]) -> bool:
    if not scope:
        return True
    return bool(scope & ({capability_ref} | aliases))


async def call_consumer_mcp_tool(
    *,
    task_id: str | None,
    tool_name: str,
    capability_ref: str,
    payload: Dict[str, Any],
    aliases: set[str] | None = None,
    user_tool_name: str | None = None,
) -> str:
    """Call the hotel consumer's generic MCP callback endpoint.

    ``tool_name`` is the internal Charmdeer MCP name, for example
    ``order.search``. ``capability_ref`` is the enterprise capability used in
    ``allowedCapabilityRefs`` and ``credentialBroker.scope``.
    """
    import asyncio
    import aiohttp

    aliases = set(aliases or set())
    display_name = user_tool_name or capability_ref
    enterprise_context = get_enterprise_context(task_id)

    allowed_capabilities = string_set(enterprise_context.get("allowed_capabilities"))
    if not _scope_allows(allowed_capabilities, capability_ref, aliases):
        return tool_error(
            kind="permission_denied",
            code="CAPABILITY_NOT_ALLOWED",
            message=f"{display_name} is not allowed for this enterprise turn.",
            user_message="当前会话没有调用该酒店工具的权限。",
            recoverable=False,
        )

    credential_scope = string_set(enterprise_context.get("credential_scope"))
    if not _scope_allows(credential_scope, capability_ref, aliases):
        return tool_error(
            kind="permission_denied",
            code="CREDENTIAL_SCOPE_DENIED",
            message=f"The enterprise credentialRef is not scoped for {display_name}.",
            user_message="当前凭证不能调用该酒店工具，请刷新页面或重新登录后再试。",
            recoverable=False,
        )

    credential_ref = enterprise_context.get("credentialRef")
    if not credential_ref:
        return tool_error(
            kind="credential_required",
            code="CREDENTIAL_REQUIRED",
            message=f"Missing enterprise credentialRef for {display_name}.",
            user_message="当前酒店工具凭证缺失，请刷新页面或重新登录后再试。",
            recoverable=False,
        )

    url = f"{hotel_api_base_url()}/services/hermesConsumer/tools/mcpCall"
    body = {
        "token": credential_ref,
        "tool": tool_name,
        "payload": payload or {},
    }
    timeout_seconds = hotel_timeout_seconds()
    logger.info(
        "%s calling consumer MCP tool=%s timeout=%.1fs payload_keys=%s",
        display_name,
        tool_name,
        timeout_seconds,
        sorted((payload or {}).keys()),
    )
    timeout = aiohttp.ClientTimeout(
        total=timeout_seconds,
        sock_connect=min(10.0, timeout_seconds),
        sock_read=timeout_seconds,
    )
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=body) as response:
                text = await response.text()
                try:
                    data = json.loads(text) if text else {}
                except json.JSONDecodeError:
                    data = {"raw": text}

                result = extract_hermes_tool_result(data)
                if response.status >= 400:
                    error = result.get("error") if isinstance(result, dict) else result
                    if not isinstance(error, dict):
                        error = {"message": str(error or "Hotel MCP backend failed.")}
                    error.setdefault("code", "BACKEND_ERROR")
                    error.setdefault("missingFields", [])
                    error.setdefault("userMessage", error.get("message") or "酒店工具调用失败，请稍后再试。")
                    error.setdefault(
                        "modelGuidance",
                        "Explain the backend error briefly and ask for corrected details if needed.",
                    )
                    error.setdefault("nextActions", [])
                    return json.dumps({
                        "ok": False,
                        "kind": "invalid_argument" if response.status < 500 else "backend_unavailable",
                        "status": response.status,
                        "recoverable": response.status < 500,
                        "error": error,
                    }, ensure_ascii=False)
                return json.dumps(result, ensure_ascii=False)
    except (asyncio.TimeoutError, TimeoutError):
        logger.warning(
            "%s timed out after %.1fs calling %s tool=%s payload_keys=%s",
            display_name,
            timeout_seconds,
            url,
            tool_name,
            sorted((payload or {}).keys()),
        )
        return tool_error(
            kind="timeout",
            code="TOOL_TIMEOUT",
            message=f"Hotel MCP backend did not respond within {timeout_seconds:.0f}s.",
            user_message="酒店工具调用暂时超时了，请缩小查询范围或稍后再试。",
            model_guidance="Tell the user the backend timed out and suggest narrowing the query.",
            next_actions=["ask_user_to_narrow_query_or_retry"],
        )
    except aiohttp.ClientError as exc:
        logger.warning("%s request failed calling %s tool=%s: %s", display_name, url, tool_name, exc)
        return tool_error(
            kind="backend_unavailable",
            code="BACKEND_UNAVAILABLE",
            message=str(exc),
            user_message="酒店工具服务暂时不可用，请稍后再试。",
            model_guidance="Tell the user the hotel backend is unavailable and suggest retrying later.",
            next_actions=["ask_user_to_retry_later"],
        )
