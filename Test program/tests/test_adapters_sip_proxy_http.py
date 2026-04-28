from __future__ import annotations

import io
import json
import urllib.error
import urllib.request

import pytest

from ims_tester.adapters import SipProxyHttpTransport


class _DummyResponse:
    def __init__(self, body: bytes):
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_DummyResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def test_sip_proxy_http_transport_requires_api_base_url() -> None:
    with pytest.raises(ValueError):
        SipProxyHttpTransport({})


def test_normalize_target_uri_handles_host_port_and_ipv6() -> None:
    transport = SipProxyHttpTransport(
        {
            "api_base_url": "http://example.test",
            "check_health_on_open": False,
            "default_target_transport": "udp",
            "default_target_port": 5060,
        }
    )

    assert transport._normalize_target_uri("10.0.0.10") == "sip:10.0.0.10:5060;transport=udp"
    assert transport._normalize_target_uri("example.com:5070") == "sip:example.com:5070;transport=udp"
    assert transport._normalize_target_uri("[2001:db8::1]:5070") == "sip:[2001:db8::1]:5070;transport=udp"
    assert transport._normalize_target_uri("2001:db8::1") == "sip:[2001:db8::1]:5060;transport=udp"
    assert transport._normalize_target_uri("<sip:alice@example.com>") == "sip:alice@example.com"


def test_normalize_target_uri_rejects_empty() -> None:
    transport = SipProxyHttpTransport({"api_base_url": "http://example.test", "check_health_on_open": False})
    with pytest.raises(ValueError):
        transport._normalize_target_uri("   ")


def test_execute_json_request_parses_mapping_json(monkeypatch) -> None:
    transport = SipProxyHttpTransport({"api_base_url": "http://example.test", "check_health_on_open": False})

    def fake_urlopen(request, timeout):
        assert timeout >= 0.2
        return _DummyResponse(b"{\"status\": \"ok\"}")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    request = urllib.request.Request("http://example.test/health", method="GET")
    result = transport._execute_json_request(request, timeout=0.1)
    assert result == {"status": "ok"}


def test_execute_json_request_rejects_invalid_or_non_mapping_json(monkeypatch) -> None:
    transport = SipProxyHttpTransport({"api_base_url": "http://example.test", "check_health_on_open": False})

    def fake_urlopen_invalid(request, timeout):
        return _DummyResponse(b"not json")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen_invalid)
    request = urllib.request.Request("http://example.test/x", method="GET")
    with pytest.raises(RuntimeError, match="Invalid JSON"):
        transport._execute_json_request(request, timeout=1.0)

    def fake_urlopen_list(request, timeout):
        return _DummyResponse(json.dumps(["a"]).encode("utf-8"))

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen_list)
    with pytest.raises(RuntimeError, match="Unexpected JSON response"):
        transport._execute_json_request(request, timeout=1.0)


def test_execute_json_request_wraps_http_and_url_errors(monkeypatch) -> None:
    transport = SipProxyHttpTransport({"api_base_url": "http://example.test", "check_health_on_open": False})

    http_exc = urllib.error.HTTPError(
        url="http://example.test/x",
        code=500,
        msg="Internal Server Error",
        hdrs=None,
        fp=io.BytesIO(b"{\"error\":\"no\"}"),
    )

    def fake_urlopen_http(request, timeout):
        raise http_exc

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen_http)
    request = urllib.request.Request("http://example.test/x", method="GET")
    with pytest.raises(RuntimeError, match=r"HTTP error from sip_proxy API: 500"):
        transport._execute_json_request(request, timeout=1.0)

    def fake_urlopen_url(request, timeout):
        raise urllib.error.URLError("boom")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen_url)
    with pytest.raises(RuntimeError, match="Cannot reach sip_proxy API"):
        transport._execute_json_request(request, timeout=1.0)


def test_send_and_read_use_post_json_without_network(monkeypatch, device_pixel) -> None:
    transport = SipProxyHttpTransport(
        {
            "api_base_url": "http://example.test",
            "check_health_on_open": False,
        }
    )

    posted = []

    def fake_post_json(path: str, payload, timeout: float):
        posted.append((path, dict(payload)))
        if path.endswith("/tester/send"):
            return {"correlation_id": "abc"}
        if path.endswith("/tester/read"):
            return {"responses": ["SIP/2.0 200 OK\r\n\r\n", "SIP/2.0 404 Not Found\r\n\r\n"]}
        return {}

    monkeypatch.setattr(transport, "_post_json", fake_post_json)

    transport.open()
    try:
        corr = transport.send(device_pixel, "REGISTER sip:x SIP/2.0\r\n\r\n", {})
        assert corr == "abc"

        responses = transport.read(device_pixel, corr, timeout_seconds=1.0)
        assert [r.status_code for r in responses] == [200, 404]

        assert posted[0][0].endswith("/tester/send")
        assert posted[1][0].endswith("/tester/read")
    finally:
        transport.close()
