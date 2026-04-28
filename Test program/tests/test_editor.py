from __future__ import annotations

import pytest

from ims_tester.editor import BasicSipMessageModifier, parse_raw_sip_message, render_raw_sip_message
from ims_tester.models import MessageEdit


def test_parse_raw_sip_message_normalizes_crlf_and_extracts_body() -> None:
    raw = "SIP/2.0 200 OK\r\nVia: 1\r\n\r\nhello"
    parsed = parse_raw_sip_message(raw)
    assert parsed.start_line == "SIP/2.0 200 OK"
    assert parsed.headers == ["Via: 1"]
    assert parsed.body == "hello"


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "\r\n\r\n",
        "\n\n",
        "   \n\nbody",
    ],
)
def test_parse_raw_sip_message_raises_on_empty_or_missing_start_line(raw: str) -> None:
    with pytest.raises(ValueError):
        parse_raw_sip_message(raw)


def test_render_raw_sip_message_uses_crlf_and_double_crlf_separator() -> None:
    parsed = parse_raw_sip_message("SIP/2.0 100 Trying\nHeader: v\n\n")
    rendered = render_raw_sip_message(parsed)
    assert "\r\n\r\n" in rendered
    assert rendered.startswith("SIP/2.0 100 Trying\r\nHeader: v\r\n\r\n")


def test_modifier_apply_no_edits_preserves_template_exactly() -> None:
    template = "INVITE sip:x SIP/2.0\r\nBadHeader\r\n\r\nBODY"
    modifier = BasicSipMessageModifier()
    assert modifier.apply(template, []) == template


def test_modifier_can_set_start_line() -> None:
    template = "INVITE sip:x SIP/2.0\r\n\r\n"
    modifier = BasicSipMessageModifier()
    out = modifier.apply(
        template,
        [MessageEdit(target="start_line", action="set", value="REGISTER sip:y SIP/2.0")],
    )
    assert out.startswith("REGISTER sip:y SIP/2.0\r\n")


def test_modifier_corrupts_start_line_with_regex_replacement() -> None:
    template = "INVITE sip:x SIP/2.0\r\n\r\n"
    modifier = BasicSipMessageModifier()
    out = modifier.apply(
        template,
        [
            MessageEdit(
                target="start_line",
                action="corrupt",
                pattern=r"INVITE",
                replacement="BAD",
            )
        ],
    )
    assert out.startswith("BAD sip:x SIP/2.0\r\n")


def test_modifier_set_header_replaces_first_occurrence_and_removes_duplicates() -> None:
    template = (
        "SIP/2.0 200 OK\r\n"
        "Via: a\r\n"
        "via: b\r\n"
        "Call-ID: 1\r\n\r\n"
    )
    modifier = BasicSipMessageModifier()
    out = modifier.apply(
        template,
        [MessageEdit(target="header", action="set", field="Via", value="new")],
    )
    # Only one Via remains.
    assert out.count("Via:") == 1
    assert "Via: new" in out
    assert "Call-ID: 1" in out


def test_modifier_appends_header_without_deduplication() -> None:
    template = "SIP/2.0 200 OK\r\nVia: a\r\n\r\n"
    modifier = BasicSipMessageModifier()
    out = modifier.apply(
        template,
        [MessageEdit(target="header", action="append", field="Via", value="b")],
    )
    assert out.count("Via:") == 2


def test_modifier_removes_header_case_insensitive() -> None:
    template = "SIP/2.0 200 OK\r\nVia: a\r\nX-Test: 1\r\n\r\n"
    modifier = BasicSipMessageModifier()
    out = modifier.apply(
        template,
        [MessageEdit(target="header", action="remove", field="vIa")],
    )
    assert "Via:" not in out
    assert "X-Test: 1" in out


def test_modifier_corrupt_header_prefixes_value_by_default() -> None:
    template = "SIP/2.0 200 OK\r\nUser-Agent: Hello\r\n\r\n"
    modifier = BasicSipMessageModifier()
    out = modifier.apply(
        template,
        [MessageEdit(target="header", action="corrupt", field="User-Agent")],
    )
    assert "User-Agent: CORRUPTED-Hello" in out


def test_modifier_corrupt_header_supports_regex_replacement() -> None:
    template = "SIP/2.0 200 OK\r\nUser-Agent: Pixel 8\r\n\r\n"
    modifier = BasicSipMessageModifier()
    out = modifier.apply(
        template,
        [
            MessageEdit(
                target="header",
                action="corrupt",
                field="User-Agent",
                pattern=r"Pixel",
                replacement="Galaxy",
            )
        ],
    )
    assert "User-Agent: Galaxy 8" in out


def test_modifier_corrupt_header_can_add_missing_header_when_value_provided() -> None:
    template = "SIP/2.0 200 OK\r\n\r\n"
    modifier = BasicSipMessageModifier()
    out = modifier.apply(
        template,
        [MessageEdit(target="header", action="corrupt", field="X-New", value="abc")],
    )
    assert "X-New: abc" in out


def test_modifier_body_set_append_and_corrupt() -> None:
    template = "INVITE sip:x SIP/2.0\r\n\r\nhello"
    modifier = BasicSipMessageModifier()

    out = modifier.apply(
        template,
        [MessageEdit(target="body", action="append", value=" world")],
    )
    assert out.endswith("\r\n\r\nhello world")

    out2 = modifier.apply(
        template,
        [MessageEdit(target="body", action="set", value="replaced")],
    )
    assert out2.endswith("\r\n\r\nreplaced")

    out3 = modifier.apply(
        template,
        [MessageEdit(target="body", action="corrupt", value="X-")],
    )
    assert out3.endswith("\r\n\r\nX-hello")
