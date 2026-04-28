from __future__ import annotations

from datetime import datetime

import pytest

from ims_tester.models import SipResponse, utc_now_iso


def test_sip_response_parse_extracts_status_reason_headers_and_body() -> None:
    raw = (
        "SIP/2.0 200 OK\r\n"
        "Via: a\r\n"
        "Via: b\r\n"
        "X-Test: one\r\n"
        "BadHeader\r\n"
        "\r\n"
        "BODY"
    )
    parsed = SipResponse.parse(raw)
    assert parsed.status_code == 200
    assert parsed.reason_phrase == "OK"
    assert parsed.body == "BODY"

    assert parsed.header_values("via") == ["a", "b"]
    assert parsed.header_values("Via") == ["a", "b"]
    assert parsed.header_values("x-test") == ["one"]


def test_sip_response_parse_empty_or_malformed_yields_status_zero() -> None:
    assert SipResponse.parse("").status_code == 0
    assert SipResponse.parse("\r\n\r\n").status_code == 0
    assert SipResponse.parse("SIP/2.0 200\r\n\r\n").status_code == 0


def test_utc_now_iso_has_z_suffix_and_no_microseconds() -> None:
    value = utc_now_iso()
    assert value.endswith("Z")
    assert "." not in value  # microseconds removed

    # datetime.fromisoformat doesn't support trailing Z; strip it.
    parsed = datetime.fromisoformat(value[:-1])
    assert isinstance(parsed, datetime)


@pytest.mark.parametrize(
    "raw,expected_status",
    [
        ("SIP/2.0 404 Not Found\r\n\r\n", 404),
        ("SIP/2.0 abc Weird\r\n\r\n", 0),
    ],
)
def test_sip_response_status_code_parsing(raw: str, expected_status: int) -> None:
    assert SipResponse.parse(raw).status_code == expected_status
