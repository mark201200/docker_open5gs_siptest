from __future__ import annotations

import pytest

from ims_tester.adapters import StubSipTransport


def test_stub_transport_requires_open(device_pixel) -> None:
    transport = StubSipTransport()

    with pytest.raises(RuntimeError):
        transport.send(device_pixel, "REGISTER sip:x SIP/2.0\r\n\r\n", {})

    with pytest.raises(RuntimeError):
        transport.read(device_pixel, "abc", 1.0)


def test_stub_transport_send_read_returns_canned_responses(device_pixel, sip_ok_response) -> None:
    transport = StubSipTransport(
        {
            "canned_responses": {
                device_pixel.device_id: {
                    "REGISTER": [sip_ok_response],
                }
            }
        }
    )
    transport.open()
    try:
        correlation = transport.send(device_pixel, "REGISTER sip:x SIP/2.0\r\n\r\n", {})
        assert isinstance(correlation, str) and len(correlation) == 32

        responses = transport.read(device_pixel, correlation, timeout_seconds=1.0)
        assert len(responses) == 1
        assert responses[0].status_code == 200
        assert responses[0].reason_phrase == "OK"
    finally:
        transport.close()


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("REGISTER sip:x SIP/2.0\r\n\r\n", "REGISTER"),
        ("INVITE sip:x SIP/2.0\r\n\r\n", "INVITE"),
        ("SIP/2.0 200 OK\r\n\r\n", "RESPONSE"),
        ("\r\n", "UNKNOWN"),
    ],
)
def test_stub_transport_extract_method(raw: str, expected: str) -> None:
    assert StubSipTransport._extract_method(raw) == expected


def test_stub_transport_canned_response_resolution_order_device_then_default(device_pixel, device_galaxy) -> None:
    transport = StubSipTransport(
        {
            "canned_responses": {
                device_pixel.device_id: {"REGISTER": "SIP/2.0 200 OK\r\n\r\n"},
                "_default": {"*": "SIP/2.0 500 Default\r\n\r\n"},
            }
        }
    )
    transport.open()
    try:
        c1 = transport.send(device_pixel, "REGISTER sip:x SIP/2.0\r\n\r\n", {})
        r1 = transport.read(device_pixel, c1, 1.0)
        assert r1 and r1[0].status_code == 200

        c2 = transport.send(device_galaxy, "REGISTER sip:x SIP/2.0\r\n\r\n", {})
        r2 = transport.read(device_galaxy, c2, 1.0)
        assert r2 and r2[0].status_code == 500
    finally:
        transport.close()


def test_stub_transport_canned_response_resolution_supports_shorthand_mapping(device_pixel) -> None:
    transport = StubSipTransport({"canned_responses": {"REGISTER": "SIP/2.0 201 Created\r\n\r\n"}})
    transport.open()
    try:
        correlation = transport.send(device_pixel, "REGISTER sip:x SIP/2.0\r\n\r\n", {})
        responses = transport.read(device_pixel, correlation, 1.0)
        assert responses and responses[0].status_code == 201
    finally:
        transport.close()


def test_stub_transport_default_response_when_nothing_configured(device_pixel) -> None:
    transport = StubSipTransport({"default_status": 404, "default_reason": "Nope"})
    transport.open()
    try:
        correlation = transport.send(device_pixel, "OPTIONS sip:x SIP/2.0\r\n\r\n", {})
        responses = transport.read(device_pixel, correlation, 1.0)
        assert responses and responses[0].status_code == 404
        assert "Nope" in responses[0].reason_phrase
    finally:
        transport.close()


def test_stub_transport_simulated_latency_is_capped_by_timeout(monkeypatch, device_pixel) -> None:
    slept = []

    def fake_sleep(value: float) -> None:
        slept.append(value)

    monkeypatch.setattr("ims_tester.adapters.time.sleep", fake_sleep)

    transport = StubSipTransport(
        {
            "simulated_latency_seconds": 2.0,
            "canned_responses": {"REGISTER": "SIP/2.0 200 OK\r\n\r\n"},
        }
    )
    transport.open()
    try:
        correlation = transport.send(device_pixel, "REGISTER sip:x SIP/2.0\r\n\r\n", {})
        transport.read(device_pixel, correlation, timeout_seconds=0.5)
        assert slept and slept[0] == pytest.approx(0.5)
    finally:
        transport.close()
