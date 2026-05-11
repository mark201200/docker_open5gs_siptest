from __future__ import annotations

import pytest

from ims_tester.adapters import KamailioForwardTransport, KamailioRpcDiscovery


def test_kamailio_forward_requires_pcscf_host() -> None:
    with pytest.raises(ValueError):
        KamailioForwardTransport({})


def test_kamailio_forward_requires_advertised_host_for_wildcard() -> None:
    with pytest.raises(ValueError):
        KamailioForwardTransport({"pcscf_host": "127.0.0.1", "listen_host": "0.0.0.0"})


def test_kamailio_forward_normalizes_target_uri() -> None:
    transport = KamailioForwardTransport(
        {
            "pcscf_host": "127.0.0.1",
            "listen_host": "127.0.0.1",
            "listen_port": 5070,
            "advertised_host": "127.0.0.1",
            "default_target_transport": "udp",
            "default_target_port": 5060,
        }
    )

    assert transport._normalize_target_uri("10.0.0.10") == "sip:10.0.0.10:5060;transport=udp"
    assert transport._normalize_target_uri("example.com:5070") == "sip:example.com:5070;transport=udp"
    assert transport._normalize_target_uri("[2001:db8::1]:5070") == "sip:[2001:db8::1]:5070;transport=udp"
    assert transport._normalize_target_uri("2001:db8::1") == "sip:[2001:db8::1]:5060;transport=udp"
    assert transport._normalize_target_uri("<sip:alice@example.com>") == "sip:alice@example.com"


def test_kamailio_forward_builds_forward_message() -> None:
    transport = KamailioForwardTransport(
        {
            "pcscf_host": "127.0.0.1",
            "listen_host": "127.0.0.1",
            "listen_port": 5070,
            "advertised_host": "192.0.2.10",
            "inject_via": True,
        }
    )

    raw_message = (
        "REGISTER sip:ims.example SIP/2.0\r\n"
        "Via: SIP/2.0/UDP 192.0.2.20;branch=z9hG4bK-1\r\n"
        "X-IMS-Tester-Target: <sip:old-target>\r\n"
        "Content-Length: 0\r\n"
        "\r\n"
    )

    branch = "z9hG4bK-ims-tester-abc"
    rendered = transport._build_forward_message(
        raw_message,
        "sip:10.0.0.10:5060;transport=udp",
        branch,
    )

    lines = rendered.split("\r\n")
    assert lines[1].startswith(
        "Via: SIP/2.0/UDP 192.0.2.10:5070;branch=z9hG4bK-ims-tester-abc;rport"
    )
    assert "X-IMS-Tester-Target: <sip:10.0.0.10:5060;transport=udp>" in rendered
    assert rendered.count("X-IMS-Tester-Target:") == 1
    assert transport._extract_top_via_branch(rendered) == branch


def test_kamailio_forward_read_drains_buffer(device_pixel) -> None:
    transport = KamailioForwardTransport(
        {
            "pcscf_host": "127.0.0.1",
            "listen_host": "127.0.0.1",
            "listen_port": 0,
            "advertised_host": "127.0.0.1",
        }
    )

    transport.open()
    try:
        transport._record_response("corr-1", "SIP/2.0 200 OK\r\n\r\n")
        responses = transport.read(device_pixel, "corr-1", timeout_seconds=0.1)
        assert [resp.status_code for resp in responses] == [200]
    finally:
        transport.close()


def test_kamailio_rpc_discovery_parses_ul_dump() -> None:
    discovery = KamailioRpcDiscovery({"rpc_socket": "/var/run/kamailio/kamailio_rpc.sock"})
    lines = [
        "Domain: location",
        "AOR: sip:+15551234567@ims.example",
        "  Contact: <sip:+15551234567@192.0.2.10:5060;transport=udp>;expires=3600",
        "    Received: sip:192.0.2.10:5060;transport=udp",
        "    User-Agent: Pixel",
    ]

    records = discovery._parse_dump_records(lines)
    assert len(records) == 1
    record = records[0]
    assert record["aor"] == "sip:+15551234567@ims.example"
    assert "sip:+15551234567@192.0.2.10:5060" in record["contact"]
    assert record["received"].startswith("sip:192.0.2.10:5060")
    assert record["user_agent"] == "Pixel"
