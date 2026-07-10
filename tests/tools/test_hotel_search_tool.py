import json

from tools.hotel_search_tool import _hotel_search_mcp_payload, _hotel_timeout_seconds, _prepare_hotel_payload


def _error_payload(result: str) -> dict:
    data = json.loads(result)
    assert data["ok"] is False
    return data


def test_hotel_payload_requires_destination_or_hotel_name():
    payload, error = _prepare_hotel_payload({
        "dateRangeStart": "2099-07-10",
        "dateRangeEnd": "2099-07-12",
    })

    assert payload is None
    data = _error_payload(error)
    assert data["kind"] == "clarification_required"
    assert data["error"]["code"] == "MISSING_SEARCH_TARGET"
    assert "destination" in data["error"]["missingFields"]


def test_hotel_payload_derives_stay_nights_for_exact_range():
    payload, error = _prepare_hotel_payload({
        "destination": "Shanghai",
        "dateRangeStart": "2099-07-10",
        "dateRangeEnd": "2099-07-12",
    })

    assert error is None
    assert payload["stayNights"] == 2
    assert payload["guestCount"] == 2


def test_hotel_payload_rejects_wide_flexible_destination_search(monkeypatch):
    monkeypatch.setenv("HERMES_HOTEL_SEARCH_WINDOW_MAX_DAYS", "7")

    payload, error = _prepare_hotel_payload({
        "destination": "Shanghai",
        "searchRangeStart": "2099-07-01",
        "searchRangeEnd": "2099-07-20",
        "stayNights": 2,
    })

    assert payload is None
    data = _error_payload(error)
    assert data["error"]["code"] == "SEARCH_WINDOW_TOO_WIDE"


def test_hotel_payload_allows_wide_window_with_hotel_name(monkeypatch):
    monkeypatch.setenv("HERMES_HOTEL_SEARCH_WINDOW_MAX_DAYS", "7")

    payload, error = _prepare_hotel_payload({
        "hotelName": "Park Hyatt",
        "searchRangeStart": "2099-07-01",
        "searchRangeEnd": "2099-07-20",
        "stayNights": 2,
    })

    assert error is None
    assert payload["hotelName"] == "Park Hyatt"


def test_hotel_search_mcp_payload_maps_exact_range_and_filter():
    mcp_payload = _hotel_search_mcp_payload({
        "hotelName": "Park Hyatt",
        "dateRangeStart": "2099-07-10",
        "dateRangeEnd": "2099-07-12",
        "guestCount": 3,
        "currency": "sgd",
    })

    assert mcp_payload["stay"]["date"] == {
        "checkIn": "2099-07-10",
        "checkOut": "2099-07-12",
    }
    assert mcp_payload["stay"]["guest"]["numberOfAdults"] == 3
    assert mcp_payload["filter"]["search"] == "Park Hyatt"
    assert mcp_payload["filter"]["upgradeToGold"] is False
    assert mcp_payload["preferred"]["currency"] == "SGD"
    assert mcp_payload["paging"]["limit"] == 10


def test_hotel_search_mcp_payload_maps_resolved_refs_and_sliding_window():
    mcp_payload = _hotel_search_mcp_payload({
        "cityRef": "668000000000000000000001",
        "moduleTpHotelRef": "668000000000000000000002",
        "searchRangeStart": "2099-07-10",
        "searchRangeEnd": "2099-07-20",
        "stayNights": 2,
        "isDBS": True,
    })

    assert mcp_payload["stay"]["date"] == {
        "checkIn": "2099-07-10",
        "checkOut": "2099-07-12",
    }
    assert mcp_payload["filter"]["hotels"] == [{"_id": "668000000000000000000002"}]
    assert mcp_payload["filter"]["upgradeToGold"] is True


def test_hotel_timeout_is_capped(monkeypatch):
    monkeypatch.setenv("HERMES_HOTEL_API_TIMEOUT_SECONDS", "300")
    monkeypatch.setenv("HERMES_HOTEL_API_MAX_TIMEOUT_SECONDS", "60")

    assert _hotel_timeout_seconds() == 60
