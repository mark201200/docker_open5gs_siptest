from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Sequence, Tuple

from .interfaces import SipMessageModifier
from .models import MessageEdit


@dataclass
class ParsedSipMessage:
    start_line: str
    headers: List[str]
    body: str


def parse_raw_sip_message(raw: str) -> ParsedSipMessage:
    normalized = raw.replace("\r\n", "\n")
    head, _, body = normalized.partition("\n\n")
    lines = [line for line in head.split("\n")]
    if not lines or not lines[0].strip():
        raise ValueError("SIP message template is empty or malformed")
    return ParsedSipMessage(start_line=lines[0].strip(), headers=lines[1:], body=body)


def render_raw_sip_message(message: ParsedSipMessage) -> str:
    return "\r\n".join([message.start_line] + message.headers) + "\r\n\r\n" + message.body


def _split_header_line(header_line: str) -> Tuple[str, str]:
    if ":" not in header_line:
        return "", ""
    name, value = header_line.split(":", 1)
    return name.strip(), value.strip()


def _set_or_replace_header(headers: List[str], name: str, value: str) -> None:
    target = name.lower()
    replaced = False
    new_headers: List[str] = []
    for line in headers:
        h_name, _ = _split_header_line(line)
        if h_name.lower() == target:
            if not replaced:
                new_headers.append(f"{name}: {value}")
                replaced = True
        else:
            new_headers.append(line)
    if not replaced:
        new_headers.append(f"{name}: {value}")
    headers[:] = new_headers


class BasicSipMessageModifier(SipMessageModifier):
    """
    Minimal, interface-based modifier for test scaffolding.

    It supports deterministic edits over start line, headers, and body so the
    test engine can be exercised before real IMS transport backends are added.
    """

    def apply(self, template: str, edits: Sequence[MessageEdit]) -> str:
        if not edits:
            # Preserve the template exactly (including intentionally malformed headers).
            return template

        parsed = parse_raw_sip_message(template)

        for edit in edits:
            target = edit.target.lower()
            action = edit.action.lower()

            if target == "start_line":
                self._edit_start_line(parsed, action, edit)
            elif target == "header":
                self._edit_header(parsed, action, edit)
            elif target == "body":
                self._edit_body(parsed, action, edit)

        return render_raw_sip_message(parsed)

    def _edit_start_line(self, parsed: ParsedSipMessage, action: str, edit: MessageEdit) -> None:
        if action == "set" and edit.value is not None:
            parsed.start_line = edit.value
            return

        if action == "corrupt":
            if edit.pattern is not None:
                replacement = edit.replacement or ""
                parsed.start_line = re.sub(edit.pattern, replacement, parsed.start_line)
            else:
                parsed.start_line = parsed.start_line + " CORRUPTED"

    def _edit_header(self, parsed: ParsedSipMessage, action: str, edit: MessageEdit) -> None:
        if not edit.field:
            return

        target = edit.field.lower()

        if action == "remove":
            parsed.headers = [line for line in parsed.headers if _split_header_line(line)[0].lower() != target]
            return

        if action == "append":
            header_value = edit.value or ""
            parsed.headers.append(f"{edit.field}: {header_value}")
            return

        if action == "set":
            _set_or_replace_header(parsed.headers, edit.field, edit.value or "")
            return

        if action != "corrupt":
            return

        new_headers: List[str] = []
        found = False
        for line in parsed.headers:
            h_name, h_value = _split_header_line(line)
            if h_name.lower() != target:
                new_headers.append(line)
                continue

            found = True
            if edit.value is not None:
                new_headers.append(f"{h_name}: {edit.value}")
            elif edit.pattern is not None:
                replacement = edit.replacement or ""
                new_headers.append(f"{h_name}: {re.sub(edit.pattern, replacement, h_value)}")
            else:
                new_headers.append(f"{h_name}: CORRUPTED-{h_value}")

        if not found and edit.value is not None:
            new_headers.append(f"{edit.field}: {edit.value}")

        parsed.headers = new_headers

    def _edit_body(self, parsed: ParsedSipMessage, action: str, edit: MessageEdit) -> None:
        if action == "set":
            parsed.body = edit.value or ""
            return

        if action == "append":
            parsed.body = parsed.body + (edit.value or "")
            return

        if action == "corrupt":
            if edit.pattern is not None:
                replacement = edit.replacement or ""
                parsed.body = re.sub(edit.pattern, replacement, parsed.body)
            else:
                parsed.body = (edit.value or "CORRUPTED-BODY") + parsed.body
