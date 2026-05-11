from __future__ import annotations

import time
from typing import Any, Dict, List, Mapping, Optional

from .interfaces import SipMessageModifier, SipTransport
from .models import (
    CaseResult,
    ComparisonCaseResult,
    ComparisonIteration,
    ComparisonReport,
    ComplianceReport,
    DeviceProfile,
    ExpectedResponse,
    IterationResult,
    MessageEdit,
    SipResponse,
    TestCase,
    TestSuite,
    utc_now_iso,
)


class ComplianceTestRunner:
    def __init__(self, transport: SipTransport, modifier: SipMessageModifier) -> None:
        self.transport = transport
        self.modifier = modifier

    def run(
        self,
        suite: TestSuite,
        device: DeviceProfile,
        *,
        wait_for_enter_between_cases: bool = True,
    ) -> ComplianceReport:
        started = utc_now_iso()

        case_results: List[CaseResult] = []
        try:
            total_cases = len(suite.cases)
            for case_index, case in enumerate(suite.cases, start=1):
                case_results.append(self._run_case(case, suite.default_timeout_seconds, suite.suite_id, device))
                _pause_before_next_case(case_index, total_cases, wait_for_enter_between_cases)
        finally:
            _replace_live_edit_rules(self.transport, [])

        passed_cases = sum(1 for case in case_results if case.passed)
        return ComplianceReport(
            suite_id=suite.suite_id,
            suite_title=suite.title,
            device_id=device.device_id,
            started_at_utc=started,
            finished_at_utc=utc_now_iso(),
            total_cases=len(case_results),
            passed_cases=passed_cases,
            case_results=case_results,
        )

    def _run_case(
        self,
        case: TestCase,
        default_timeout_seconds: float,
        suite_id: str,
        device: DeviceProfile,
    ) -> CaseResult:
        rules = _build_intercept_rules(case, device)
        _replace_live_edit_rules(self.transport, rules)

        if case.message.intercept_only:
            return self._run_intercept_only_case(case, default_timeout_seconds, rules, device)

        count = case.message.repeat.count
        rate = case.message.repeat.rate_per_second
        interval = 1.0 / rate if rate > 0 else 0.0
        timeout_seconds = case.timeout_seconds if case.timeout_seconds is not None else default_timeout_seconds

        iterations: List[IterationResult] = []
        for iteration in range(1, count + 1):
            sent_message = _render_message_for_device(
                modifier=self.modifier,
                device=device,
                template=case.message.template,
                edits=case.message.edits,
            )
            print(
                f"Sending {_message_type_label(case.message.message_type)} message to device {_device_label(device)}"
            )
            correlation_id = self.transport.send(
                device,
                sent_message,
                {
                    "suite_id": suite_id,
                    "case_id": case.case_id,
                    "iteration": iteration,
                    "message_type": case.message.message_type,
                },
            )

            print(
                f"Waiting for {_message_type_label(case.message.message_type)} response from device {_device_label(device)}"
            )
            responses = list(self.transport.read(device, correlation_id, timeout_seconds))
            if responses:
                print(
                    f"Received {_format_response_summary(responses[0])} response from device {_device_label(device)}"
                )
            else:
                print(
                    f"Received no response from device {_device_label(device)}"
                )
            passed, mismatches = self._validate_expected(case.expected_response, responses)
            iterations.append(
                IterationResult(
                    iteration=iteration,
                    passed=passed,
                    mismatches=mismatches,
                    sent_message=sent_message,
                    responses=responses,
                )
            )

            if iteration < count and interval > 0:
                time.sleep(interval)

        return CaseResult(
            case_id=case.case_id,
            description=case.description,
            passed=all(item.passed for item in iterations),
            iterations=iterations,
        )

    def _run_intercept_only_case(
        self,
        case: TestCase,
        default_timeout_seconds: float,
        rules: List[Dict[str, Any]],
        device: DeviceProfile,
    ) -> CaseResult:
        count = case.message.repeat.count
        interval = 0.0
        if case.message.repeat.rate_per_second > 0:
            interval = 1.0 / case.message.repeat.rate_per_second

        timeout_seconds = case.timeout_seconds
        if timeout_seconds is None:
            timeout_seconds = case.message.intercept_wait_timeout_seconds or default_timeout_seconds
        if timeout_seconds <= 0:
            timeout_seconds = default_timeout_seconds

        rule_ids = [str(rule.get("id", "")).strip() for rule in rules if str(rule.get("id", "")).strip()]
        method_filter = case.message.intercept_message_type
        direction_filter = case.message.intercept_direction

        iterations: List[IterationResult] = []
        for iteration in range(1, count + 1):
            print(
                "Waiting for a "
                f"{_message_type_label(method_filter)} {_intercept_direction_label(direction_filter)} "
                f"to intercept from device {_device_label(device)}"
            )
            wait_result = _wait_for_live_edit_match(
                transport=self.transport,
                rule_ids=rule_ids,
                timeout_seconds=timeout_seconds,
                method=method_filter,
                direction=direction_filter,
            )

            ignored_hits_raw = wait_result.get("ignored_hits", [])
            if isinstance(ignored_hits_raw, list):
                for ignored_hit in ignored_hits_raw:
                    if not isinstance(ignored_hit, Mapping):
                        continue
                    start_line = str(ignored_hit.get("start_line", "")).strip() or "<unknown>"
                    required_direction = str(
                        ignored_hit.get("required_direction", direction_filter)
                    ).strip().lower()
                    if required_direction in {"request", "response"}:
                        print(
                            f"Ignoring message {start_line}: only looking for {required_direction} messages"
                        )

            matched = bool(wait_result.get("matched"))
            mismatches: List[str] = []
            if not matched:
                print(
                    f"Received no intercepted message from device {_device_label(device)}"
                )
                mismatches.append(
                    "No matching live SIP message observed "
                    f"within {timeout_seconds:.1f}s for method={method_filter} direction={direction_filter}"
                )
            else:
                matched_direction = str(wait_result.get("matched_direction", direction_filter)).strip().lower() or "any"
                matched_method = str(wait_result.get("matched_method", method_filter)).strip() or method_filter
                print(
                    "Received intercepted "
                    f"{_message_type_label(matched_method)} {_intercept_direction_label(matched_direction)} "
                    f"from device {_device_label(device)}"
                )

            iterations.append(
                IterationResult(
                    iteration=iteration,
                    passed=matched,
                    mismatches=mismatches,
                    sent_message="",
                    responses=[],
                )
            )

            if iteration < count and interval > 0:
                time.sleep(interval)

        return CaseResult(
            case_id=case.case_id,
            description=case.description,
            passed=all(item.passed for item in iterations),
            iterations=iterations,
        )

    def _validate_expected(self, expected: ExpectedResponse, responses: List[SipResponse]) -> tuple[bool, List[str]]:
        mismatches: List[str] = []

        if not responses:
            mismatches.append("No SIP response captured")
            return False, mismatches

        response = responses[0]

        if expected.status_code is not None and response.status_code != expected.status_code:
            mismatches.append(
                f"status_code mismatch: expected {expected.status_code}, got {response.status_code}"
            )

        for expected_fragment in expected.reason_contains:
            if expected_fragment.lower() not in response.reason_phrase.lower():
                mismatches.append(
                    f"reason phrase does not contain '{expected_fragment}' (actual: '{response.reason_phrase}')"
                )

        for header_name, expected_fragment in expected.header_contains.items():
            values = response.header_values(header_name)
            if not values:
                mismatches.append(f"header '{header_name}' not present")
                continue
            if not any(expected_fragment.lower() in value.lower() for value in values):
                mismatches.append(
                    f"header '{header_name}' does not contain '{expected_fragment}' (actual: {values})"
                )

        for header_name in expected.header_absent:
            if response.header_values(header_name):
                mismatches.append(f"header '{header_name}' should be absent but is present")

        for expected_fragment in expected.body_contains:
            if expected_fragment.lower() not in response.body.lower():
                mismatches.append(f"response body does not contain '{expected_fragment}'")

        return (not mismatches), mismatches


class DifferentialTestRunner:
    def __init__(self, transport: SipTransport, modifier: SipMessageModifier) -> None:
        self.transport = transport
        self.modifier = modifier

    def run(
        self,
        suite: TestSuite,
        *devices: DeviceProfile,
        wait_for_enter_between_cases: bool = True,
    ) -> ComparisonReport:
        if len(devices) < 2:
            raise RuntimeError("compare mode requires at least two devices")

        started = utc_now_iso()
        selected_device_ids = [device.device_id for device in devices]

        case_results: List[ComparisonCaseResult] = []
        try:
            total_cases = len(suite.cases)
            for case_index, case in enumerate(suite.cases, start=1):
                case_results.append(
                    self._run_case(case, suite.default_timeout_seconds, suite.suite_id, list(devices))
                )
                _pause_before_next_case(case_index, total_cases, wait_for_enter_between_cases)
        finally:
            _replace_live_edit_rules(self.transport, [])

        cases_with_differences = sum(1 for case in case_results if case.differences_found)
        return ComparisonReport(
            suite_id=suite.suite_id,
            suite_title=suite.title,
            device_a=devices[0].device_id,
            device_b=devices[1].device_id,
            started_at_utc=started,
            finished_at_utc=utc_now_iso(),
            total_cases=len(case_results),
            cases_with_differences=cases_with_differences,
            case_results=case_results,
            device_ids=selected_device_ids,
        )

    def _run_case(
        self,
        case: TestCase,
        default_timeout_seconds: float,
        suite_id: str,
        devices: List[DeviceProfile],
    ) -> ComparisonCaseResult:
        if case.message.intercept_only:
            raise RuntimeError(
                "intercept_only tests are not supported in compare mode; use run-standard"
            )

        _replace_live_edit_rules(self.transport, _build_intercept_rules(case, None))

        count = case.message.repeat.count
        rate = case.message.repeat.rate_per_second
        interval = 1.0 / rate if rate > 0 else 0.0
        timeout_seconds = case.timeout_seconds if case.timeout_seconds is not None else default_timeout_seconds

        iterations: List[ComparisonIteration] = []

        for iteration in range(1, count + 1):
            sent_messages: Dict[str, str] = {}
            correlation_ids: Dict[str, str] = {}
            responses_by_device: Dict[str, Optional[SipResponse]] = {}

            for device_index, device in enumerate(devices):
                sent_messages[device.device_id] = _render_message_for_device(
                    modifier=self.modifier,
                    device=device,
                    template=case.message.template,
                    edits=case.message.edits,
                )

                print(
                    f"Sending {_message_type_label(case.message.message_type)} message to device {_device_label(device)}"
                )
                correlation_ids[device.device_id] = self.transport.send(
                    device,
                    sent_messages[device.device_id],
                    {
                        "suite_id": suite_id,
                        "case_id": case.case_id,
                        "iteration": iteration,
                        "message_type": case.message.message_type,
                        "device_index": device_index,
                        "device_role": chr(ord("A") + device_index) if device_index < 26 else str(device_index + 1),
                    },
                )

            for device in devices:
                print(
                    f"Waiting for {_message_type_label(case.message.message_type)} response from device {_device_label(device)}"
                )
                responses = list(
                    self.transport.read(device, correlation_ids[device.device_id], timeout_seconds)
                )
                response = responses[0] if responses else None
                responses_by_device[device.device_id] = response
                if response is not None:
                    print(
                        f"Received {_format_response_summary(response)} response from device {_device_label(device)}"
                    )
                else:
                    print(f"Received no response from device {_device_label(device)}")

            baseline_device = devices[0]
            baseline_response = responses_by_device.get(baseline_device.device_id)

            differences: List[str] = []
            for device in devices[1:]:
                differences.extend(
                    self._compare_responses(
                        baseline_response,
                        responses_by_device.get(device.device_id),
                        baseline_device.device_id,
                        device.device_id,
                    )
                )

            second_device_response = responses_by_device.get(devices[1].device_id) if len(devices) > 1 else None
            iterations.append(
                ComparisonIteration(
                    iteration=iteration,
                    differences=differences,
                    response_a=baseline_response,
                    response_b=second_device_response,
                    responses_by_device=responses_by_device,
                )
            )

            if iteration < count and interval > 0:
                time.sleep(interval)

        return ComparisonCaseResult(
            case_id=case.case_id,
            description=case.description,
            differences_found=any(it.differences for it in iterations),
            iterations=iterations,
        )

    def _compare_responses(
        self,
        response_a: Optional[SipResponse],
        response_b: Optional[SipResponse],
        device_a_id: str,
        device_b_id: str,
    ) -> List[str]:
        differences: List[str] = []

        if response_a is None and response_b is None:
            return differences
        if response_a is None:
            differences.append(f"baseline device {device_a_id} produced no response")
            return differences
        if response_b is None:
            differences.append(f"device {device_b_id} produced no response")
            return differences

        if response_a.status_code != response_b.status_code:
            differences.append(
                f"status_code differs: A={response_a.status_code}, B={response_b.status_code}"
            )

        if response_a.reason_phrase.strip() != response_b.reason_phrase.strip():
            differences.append(
                f"reason_phrase differs: A='{response_a.reason_phrase}', B='{response_b.reason_phrase}'"
            )

        normalized_headers_a = _normalize_sip_headers(response_a.headers)
        normalized_headers_b = _normalize_sip_headers(response_b.headers)
        all_headers = sorted(set(normalized_headers_a.keys()) | set(normalized_headers_b.keys()))
        for header_name in all_headers:
            values_a = normalized_headers_a.get(header_name, [])
            values_b = normalized_headers_b.get(header_name, [])
            if values_a != values_b:
                differences.append(f"header '{header_name}' differs: A={values_a}, B={values_b}")

        if _normalize_sip_body(response_a.body) != _normalize_sip_body(response_b.body):
            differences.append("response body differs")

        return differences


def _normalize_sip_headers(headers: Mapping[str, List[str]]) -> Dict[str, List[str]]:
    normalized: Dict[str, List[str]] = {}
    for header_name, values in headers.items():
        cleaned_values = sorted({str(value).strip() for value in values if str(value).strip()})
        if cleaned_values:
            normalized[header_name.lower().strip()] = cleaned_values
    return normalized


def _normalize_sip_body(body: str) -> str:
    normalized_lines = [line.rstrip() for line in str(body).replace("\r\n", "\n").split("\n")]
    return "\n".join(normalized_lines).strip()


def _device_metadata_value(device: DeviceProfile, *keys: str) -> str:
    for key in keys:
        value = str(device.metadata.get(key, "")).strip()
        if value:
            return value
    return ""


def _device_label(device: DeviceProfile) -> str:
    value = device.device_id.strip()
    if value:
        return value
    return device.display_name.strip() or "<unknown>"


def _message_type_label(message_type: str) -> str:
    value = (message_type or "SIP").strip().upper()
    return value or "SIP"


def _intercept_direction_label(direction: str) -> str:
    value = (direction or "any").strip().lower()
    if value == "request":
        return "request"
    if value == "response":
        return "response"
    return "request/response"


def _format_response_summary(response: SipResponse) -> str:
    if response.status_code > 0:
        reason = response.reason_phrase.strip()
        return f"{response.status_code} {reason}".strip()
    return "unknown"


def _build_message_placeholders(device: DeviceProfile) -> Dict[str, str]:
    phone_number = _device_metadata_value(device, "phone_number", "phone", "msisdn")
    imsi = _device_metadata_value(device, "imsi")
    phone_number_or_imsi = phone_number or imsi
    phone_sip_uri = f"sip:{phone_number_or_imsi}" if phone_number_or_imsi else ""
    phone_tel_uri = f"tel:{phone_number_or_imsi}" if phone_number_or_imsi else ""

    return {
        "$DEVICE_ID": device.device_id,
        "$DEVICE_NAME": device.display_name,
        "$DEVICE_ADDRESS": device.address,
        "$PHONE": phone_number_or_imsi,
        "$PHONE_NUMBER": phone_number,
        "$PHONE_SIP_URI": phone_sip_uri,
        "$PHONE_TEL_URI": phone_tel_uri,
        "$IMSI": imsi,
        "$IMSI_URI": f"sip:{imsi}" if imsi else "",
    }


def _substitute_placeholders(value: str, placeholders: Mapping[str, str]) -> str:
    rendered = value

    # Replace longer tokens first so a shorter token (e.g. $PHONE) doesn't
    # partially replace a longer token (e.g. $PHONE_SIP_URI).
    for token in sorted(placeholders.keys(), key=len, reverse=True):
        replacement = placeholders.get(token, "")
        if replacement:
            rendered = rendered.replace(token, replacement)

    return rendered


def _render_message_for_device(
    modifier: SipMessageModifier,
    device: DeviceProfile,
    template: str,
    edits: List[MessageEdit],
) -> str:
    placeholders = _build_message_placeholders(device)
    rendered_template = _substitute_placeholders(template, placeholders)

    rendered_edits = [
        MessageEdit(
            target=edit.target,
            action=edit.action,
            field=_substitute_placeholders(edit.field, placeholders) if edit.field is not None else None,
            value=_substitute_placeholders(edit.value, placeholders) if edit.value is not None else None,
            pattern=_substitute_placeholders(edit.pattern, placeholders) if edit.pattern is not None else None,
            replacement=(
                _substitute_placeholders(edit.replacement, placeholders)
                if edit.replacement is not None
                else None
            ),
        )
        for edit in edits
    ]

    return modifier.apply(rendered_template, rendered_edits)


def _normalize_host_for_match(value: str) -> str:
    candidate = (value or "").strip().lower()
    if not candidate:
        return ""

    if candidate.startswith("[") and candidate.endswith("]"):
        candidate = candidate[1:-1].strip()

    return candidate


def _extract_host_from_target(value: str) -> str:
    raw_value = (value or "").strip()
    if not raw_value:
        return ""

    if raw_value.startswith("<") and raw_value.endswith(">"):
        raw_value = raw_value[1:-1].strip()

    lowered = raw_value.lower()
    if lowered.startswith("sip:"):
        raw_value = raw_value[4:]
    elif lowered.startswith("sips:"):
        raw_value = raw_value[5:]

    if "@" in raw_value:
        raw_value = raw_value.split("@", 1)[1]

    raw_value = raw_value.split(";", 1)[0].strip()
    raw_value = raw_value.split("?", 1)[0].strip()

    if raw_value.startswith("[") and "]" in raw_value:
        end = raw_value.find("]")
        return _normalize_host_for_match(raw_value[1:end])

    if raw_value.count(":") == 1:
        host_part, port_part = raw_value.rsplit(":", 1)
        if port_part.isdigit():
            return _normalize_host_for_match(host_part)

    # Hostnames and non-bracketed IPv6 literals are retained as-is.
    return _normalize_host_for_match(raw_value)


def _selected_device_host(device: Optional[DeviceProfile]) -> str:
    if device is None:
        return ""

    target_uri = str(device.metadata.get("target_uri", "")).strip()
    if target_uri:
        host = _extract_host_from_target(target_uri)
        if host:
            return host

    return _extract_host_from_target(device.address)


def _selected_device_phone_number(device: Optional[DeviceProfile]) -> str:
    if device is None:
        return ""

    for key in ("phone_number", "phone", "msisdn"):
        value = str(device.metadata.get(key, "")).strip()
        if value:
            return value

    return ""


def _selected_device_imsi(device: Optional[DeviceProfile]) -> str:
    if device is None:
        return ""

    return str(device.metadata.get("imsi", "")).strip()


def _device_scope_for_direction(direction: str) -> str:
    normalized = (direction or "any").strip().lower()
    if normalized == "request":
        return "source"
    if normalized == "response":
        return "destination"
    return "either"


def _build_intercept_rules(case: TestCase, selected_device: Optional[DeviceProfile]) -> List[Dict[str, Any]]:
    edits = case.message.intercept_edits
    if not edits:
        return []

    method = case.message.intercept_message_type.upper()
    if method in {"", "ANY"}:
        method = "*"

    direction = case.message.intercept_direction.lower()
    if direction not in {"request", "response", "any"}:
        direction = "request"

    selected_device_host = _selected_device_host(selected_device)
    selected_device_phone_number = _selected_device_phone_number(selected_device)
    selected_device_imsi = _selected_device_imsi(selected_device)
    selected_device_scope = _device_scope_for_direction(direction)

    rules: List[Dict[str, Any]] = []

    for index, edit in enumerate(edits, start=1):
        target = edit.target.lower()
        action = edit.action.lower()
        base_rule: Dict[str, Any] = {
            "id": f"{case.case_id}-intercept-{index}",
            "enabled": True,
            "direction": direction,
            "method": method,
        }

        if selected_device_host:
            base_rule["device_host"] = selected_device_host
            base_rule["device_scope"] = selected_device_scope
        if selected_device_phone_number:
            base_rule["device_phone_number"] = selected_device_phone_number
        if selected_device_imsi:
            base_rule["device_imsi"] = selected_device_imsi

        if target == "header" and action == "set":
            rules.append(
                {
                    **base_rule,
                    "action": "set-header",
                    "header": edit.field,
                    "value": edit.value,
                }
            )
            continue

        if target == "header" and action == "remove":
            rules.append(
                {
                    **base_rule,
                    "action": "remove-header",
                    "header": edit.field,
                }
            )
            continue

        if target == "start_line" and action == "set":
            rules.append(
                {
                    **base_rule,
                    "action": "set-start-line",
                    "value": edit.value,
                }
            )
            continue

        if target == "body" and action == "set":
            rules.append(
                {
                    **base_rule,
                    "action": "set-body",
                    "value": edit.value,
                }
            )
            continue

        raise RuntimeError(
            f"Unsupported intercept edit in case '{case.case_id}': target={target}, action={action}"
        )

    return rules


def _wait_for_live_edit_match(
    transport: SipTransport,
    rule_ids: List[str],
    timeout_seconds: float,
    method: str,
    direction: str,
) -> Dict[str, Any]:
    wait_method = getattr(transport, "wait_for_live_edit_match", None)
    if callable(wait_method):
        return wait_method(
            rule_ids=rule_ids,
            timeout_seconds=timeout_seconds,
            method=method,
            direction=direction,
        )

    raise RuntimeError(
        "intercept_only requires runtime transport 'sip-proxy-http' with live wait API support"
    )


def _replace_live_edit_rules(transport: SipTransport, rules: List[Mapping[str, Any]]) -> None:
    replace_method = getattr(transport, "replace_live_edit_rules", None)
    if callable(replace_method):
        replace_method([dict(rule) for rule in rules])
        return

    if rules:
        raise RuntimeError(
            "message.intercept_edits requires runtime transport 'sip-proxy-http' with tester live-edit API support"
        )


def _pause_before_next_case(case_index: int, total_cases: int, enabled: bool) -> None:
    if not enabled or case_index >= total_cases:
        return

    prompt = f"Press Enter to start next test ({case_index + 1}/{total_cases})..."
    try:
        input(prompt)
    except EOFError:
        print("No interactive input available; continuing to next test.")
