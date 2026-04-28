from __future__ import annotations

import pytest

from ims_tester.editor import BasicSipMessageModifier
from ims_tester.engine import _build_intercept_rules, _extract_host_from_target, _render_message_for_device, _selected_device_host
from ims_tester.models import ExpectedResponse, MessageEdit, MessageSpec, RepeatPolicy, TestCase as ModelTestCase


def test_render_message_for_device_substitutes_placeholders_in_template_and_edits(device_pixel) -> None:
    template = (
        "REGISTER $PHONE_SIP_URI SIP/2.0\r\n"
        "To: <$PHONE_SIP_URI>\r\n"
        "X-Id: $DEVICE_ID\r\n"
        "\r\n"
    )

    edits = [
        MessageEdit(
            target="header",
            action="set",
            field="X-$DEVICE_ID",
            value="$DEVICE_ADDRESS",
        )
    ]

    rendered = _render_message_for_device(
        modifier=BasicSipMessageModifier(),
        device=device_pixel,
        template=template,
        edits=edits,
    )

    assert "REGISTER sip:15551234567 SIP/2.0" in rendered
    assert "To: <sip:15551234567>" in rendered
    assert "X-Id: pixel_8" in rendered
    assert "X-pixel_8: 10.0.0.10" in rendered


def test_extract_host_from_target_handles_sip_uris_and_ipv6() -> None:
    assert _extract_host_from_target("sip:alice@10.0.0.10:5060;transport=udp") == "10.0.0.10"
    assert _extract_host_from_target("<sip:[2001:db8::1]:5060>") == "2001:db8::1"
    assert _extract_host_from_target("[2001:db8::2]") == "2001:db8::2"
    assert _extract_host_from_target("example.com:5070") == "example.com"
    assert _extract_host_from_target("2001:db8::3") == "2001:db8::3"


def test_selected_device_host_prefers_metadata_target_uri() -> None:
    from ims_tester.models import DeviceProfile

    device = DeviceProfile(
        device_id="d1",
        display_name="d1",
        address="10.0.0.1",
        metadata={"target_uri": "sip:alice@10.9.8.7:5060"},
    )
    assert _selected_device_host(device) == "10.9.8.7"


def test_build_intercept_rules_emits_expected_rule_shapes(device_pixel) -> None:
    case = ModelTestCase(
        case_id="c1",
        description="",
        message=MessageSpec(
            message_type="INVITE",
            template="",
            intercept_edits=[
                MessageEdit(target="header", action="set", field="Content-Type", value="test"),
                MessageEdit(target="header", action="remove", field="User-Agent"),
                MessageEdit(target="start_line", action="set", value="INVITE sip:x SIP/2.0"),
                MessageEdit(target="body", action="set", value="BODY"),
            ],
            intercept_direction="response",
            intercept_message_type="INVITE",
            repeat=RepeatPolicy(count=1, rate_per_second=1.0),
        ),
        expected_response=ExpectedResponse(),
    )

    rules = _build_intercept_rules(case, selected_device=device_pixel)
    assert len(rules) == 4

    assert rules[0]["id"] == "c1-intercept-1"
    assert rules[0]["direction"] == "response"
    assert rules[0]["method"] == "INVITE"
    assert rules[0]["action"] == "set-header"
    assert rules[0]["header"] == "Content-Type"
    assert rules[0]["value"] == "test"

    # Device matching fields are included when selected_device is provided.
    assert rules[0]["device_host"] == "10.0.0.10"
    assert rules[0]["device_scope"] == "destination"
    assert rules[0]["device_phone_number"] == "15551234567"
    assert rules[0]["device_imsi"] == "001010123456789"

    assert rules[1]["action"] == "remove-header"
    assert rules[2]["action"] == "set-start-line"
    assert rules[3]["action"] == "set-body"


def test_build_intercept_rules_rejects_unsupported_edits(device_pixel) -> None:
    case = ModelTestCase(
        case_id="c1",
        description="",
        message=MessageSpec(
            message_type="INVITE",
            template="",
            intercept_edits=[
                MessageEdit(target="header", action="append", field="X-Test", value="1"),
            ],
        ),
        expected_response=ExpectedResponse(),
    )

    with pytest.raises(RuntimeError, match="Unsupported intercept edit"):
        _build_intercept_rules(case, selected_device=device_pixel)
