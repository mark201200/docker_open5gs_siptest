from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Mapping

import yaml

from .errors import ConfigValidationError
from .models import (
    DeviceProfile,
    ExpectedResponse,
    MessageEdit,
    MessageSpec,
    RepeatPolicy,
    RuntimeConfig,
    RuntimeTransportConfig,
    RuntimeDiscoveryConfig,
    TestCase,
    TestSuite,
)


def load_test_suite(path: str | Path) -> TestSuite:
    file_path = Path(path)
    payload = _load_yaml_mapping(file_path)

    errors: List[str] = []

    suite_block = payload.get("suite", {})
    suite_map = _as_mapping(suite_block, "suite", errors)

    suite_id = _as_required_string(suite_map.get("id"), "suite.id", errors)
    title = _as_string(suite_map.get("title"), default=suite_id or "Untitled Suite")
    default_timeout = _as_float(suite_map.get("default_timeout_seconds", 3.0), "suite.default_timeout_seconds", errors)
    if default_timeout <= 0:
        errors.append("suite.default_timeout_seconds must be > 0")
        default_timeout = 3.0

    tests_block = payload.get("tests", [])
    if not isinstance(tests_block, list):
        errors.append("tests must be a list")
        tests_block = []

    cases: List[TestCase] = []
    seen_case_ids: set[str] = set()
    for idx, raw_case in enumerate(tests_block, start=1):
        case_path = f"tests[{idx}]"
        case_map = _as_mapping(raw_case, case_path, errors)

        case_id = _as_required_string(case_map.get("id"), f"{case_path}.id", errors)
        if case_id in seen_case_ids:
            errors.append(f"Duplicate case id '{case_id}'")
        elif case_id:
            seen_case_ids.add(case_id)

        description = _as_string(case_map.get("description"), default="")

        message_map = _as_mapping(case_map.get("message", {}), f"{case_path}.message", errors)
        intercept_only = _as_bool(message_map.get("intercept_only", False), f"{case_path}.message.intercept_only", errors)
        message_type = _as_required_string(message_map.get("type"), f"{case_path}.message.type", errors).upper()
        template = _as_string(message_map.get("template"), default="")
        if not intercept_only:
            template = _as_required_string(message_map.get("template"), f"{case_path}.message.template", errors)

        intercept_message_type = _as_string(
            message_map.get("intercept_message_type"),
            default=message_type,
        ).upper()
        if intercept_message_type in {"", "ANY"}:
            intercept_message_type = "*"

        intercept_direction = _as_string(
            message_map.get("intercept_direction"),
            default="request",
        ).lower()
        if intercept_direction not in {"request", "response", "any"}:
            errors.append(
                f"{case_path}.message.intercept_direction must be one of: request, response, any"
            )
            intercept_direction = "request"

        intercept_wait_timeout_seconds = _as_float(
            message_map.get("intercept_wait_timeout_seconds", 30.0),
            f"{case_path}.message.intercept_wait_timeout_seconds",
            errors,
        )
        if intercept_wait_timeout_seconds <= 0:
            errors.append(f"{case_path}.message.intercept_wait_timeout_seconds must be > 0")
            intercept_wait_timeout_seconds = 30.0

        edits = _parse_edits(message_map.get("edits", []), f"{case_path}.message.edits", errors)
        intercept_edits = _parse_intercept_edits(
            message_map.get("intercept_edits", []),
            f"{case_path}.message.intercept_edits",
            errors,
        )
        if intercept_only and not intercept_edits:
            errors.append(f"{case_path}.message.intercept_edits must define at least one intercept edit")
        repeat = _parse_repeat_policy(message_map.get("repeat", {}), f"{case_path}.message.repeat", errors)

        expected_map = _as_mapping(case_map.get("expected_response", {}), f"{case_path}.expected_response", errors)
        expected = _parse_expected_response(expected_map, f"{case_path}.expected_response", errors)

        timeout_seconds = None
        if "timeout_seconds" in case_map:
            timeout_seconds = _as_float(case_map.get("timeout_seconds"), f"{case_path}.timeout_seconds", errors)
            if timeout_seconds <= 0:
                errors.append(f"{case_path}.timeout_seconds must be > 0")
                timeout_seconds = None

        cases.append(
            TestCase(
                case_id=case_id,
                description=description,
                message=MessageSpec(
                    message_type=message_type,
                    template=template,
                    edits=edits,
                    intercept_edits=intercept_edits,
                    intercept_only=intercept_only,
                    intercept_message_type=intercept_message_type,
                    intercept_direction=intercept_direction,
                    intercept_wait_timeout_seconds=intercept_wait_timeout_seconds,
                    repeat=repeat,
                ),
                expected_response=expected,
                timeout_seconds=timeout_seconds,
            )
        )

    if not cases:
        errors.append("At least one test case is required in tests")

    if errors:
        raise ConfigValidationError(errors)

    return TestSuite(
        suite_id=suite_id,
        title=title,
        default_timeout_seconds=default_timeout,
        cases=cases,
    )


def load_runtime_config(path: str | Path) -> RuntimeConfig:
    file_path = Path(path)
    payload = _load_yaml_mapping(file_path)

    errors: List[str] = []

    transport_block = _as_mapping(payload.get("transport", {}), "transport", errors)
    transport_name = _as_required_string(transport_block.get("name"), "transport.name", errors).lower()
    transport_settings = transport_block.get("settings", {})
    if not isinstance(transport_settings, Mapping):
        errors.append("transport.settings must be a mapping")
        transport_settings = {}

    devices_block = payload.get("devices", [])
    if devices_block is None:
        devices_block = []
    if not isinstance(devices_block, list):
        errors.append("devices must be a list")
        devices_block = []

    devices: Dict[str, DeviceProfile] = {}
    for idx, raw_device in enumerate(devices_block, start=1):
        device_path = f"devices[{idx}]"
        device_map = _as_mapping(raw_device, device_path, errors)

        device_id = _as_required_string(device_map.get("id"), f"{device_path}.id", errors)
        display_name = _as_string(device_map.get("name"), default=device_id)
        address = _as_required_string(device_map.get("address"), f"{device_path}.address", errors)

        metadata = device_map.get("metadata", {})
        if not isinstance(metadata, Mapping):
            errors.append(f"{device_path}.metadata must be a mapping")
            metadata = {}

        if device_id in devices:
            errors.append(f"Duplicate device id '{device_id}' in runtime config")
            continue

        devices[device_id] = DeviceProfile(
            device_id=device_id,
            display_name=display_name,
            address=address,
            metadata=dict(metadata),
        )

    if not devices and transport_name != "sip-proxy-http":
        errors.append(
            "At least one device is required in runtime config unless transport.name is sip-proxy-http"
        )

    discovery_block = _as_mapping(payload.get("discovery", {}), "discovery", errors)
    discovery_method = _as_string(discovery_block.get("method", "sip-proxy"), default="sip-proxy").lower()
    if discovery_method not in {"sip-proxy", "open5gs"}:
        errors.append(
            f"discovery.method must be one of: sip-proxy, open5gs (got '{discovery_method}')"
        )
        discovery_method = "sip-proxy"
    
    discovery_settings = discovery_block.get("settings", {})
    if not isinstance(discovery_settings, Mapping):
        errors.append("discovery.settings must be a mapping")
        discovery_settings = {}

    if errors:
        raise ConfigValidationError(errors)

    return RuntimeConfig(
        transport=RuntimeTransportConfig(name=transport_name, settings=dict(transport_settings)),
        devices=devices,
        discovery=RuntimeDiscoveryConfig(method=discovery_method, settings=dict(discovery_settings)),
    )


def _load_yaml_mapping(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise ConfigValidationError([f"File not found: {path}"])

    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle)

    if payload is None:
        payload = {}

    if not isinstance(payload, Mapping):
        raise ConfigValidationError([f"Top-level YAML document must be a mapping in {path}"])

    return dict(payload)


def _as_mapping(value: Any, field: str, errors: List[str]) -> Dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    errors.append(f"{field} must be a mapping")
    return {}


def _as_string(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def _as_required_string(value: Any, field: str, errors: List[str]) -> str:
    out = _as_string(value)
    if not out:
        errors.append(f"{field} is required")
    return out


def _as_bool(value: Any, field: str, errors: List[str]) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if value is None:
        return False

    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off", ""}:
        return False

    errors.append(f"{field} must be a boolean")
    return False


def _as_float(value: Any, field: str, errors: List[str]) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        errors.append(f"{field} must be a number")
        return 0.0


def _as_int(value: Any, field: str, errors: List[str]) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        errors.append(f"{field} must be an integer")
        return 0


def _as_list(value: Any, field: str, errors: List[str]) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    errors.append(f"{field} must be a list")
    return []


def _parse_repeat_policy(value: Any, field: str, errors: List[str]) -> RepeatPolicy:
    repeat_map = _as_mapping(value or {}, field, errors)
    count = _as_int(repeat_map.get("count", 1), f"{field}.count", errors)
    rate = _as_float(repeat_map.get("rate_per_second", 1.0), f"{field}.rate_per_second", errors)

    if count < 1:
        errors.append(f"{field}.count must be >= 1")
        count = 1
    if rate <= 0:
        errors.append(f"{field}.rate_per_second must be > 0")
        rate = 1.0

    return RepeatPolicy(count=count, rate_per_second=rate)


def _parse_edits(value: Any, field: str, errors: List[str]) -> List[MessageEdit]:
    edits_raw = _as_list(value, field, errors)
    parsed: List[MessageEdit] = []

    allowed_targets = {"start_line", "header", "body"}
    allowed_actions = {"set", "remove", "append", "corrupt"}

    for idx, raw_edit in enumerate(edits_raw, start=1):
        edit_path = f"{field}[{idx}]"
        edit_map = _as_mapping(raw_edit, edit_path, errors)

        target = _as_required_string(edit_map.get("target"), f"{edit_path}.target", errors).lower()
        action = _as_required_string(edit_map.get("action"), f"{edit_path}.action", errors).lower()
        header_field = _as_string(edit_map.get("field")) or None
        message_value = _as_string(edit_map.get("value")) if edit_map.get("value") is not None else None
        pattern = _as_string(edit_map.get("pattern")) or None
        replacement = _as_string(edit_map.get("replacement")) if edit_map.get("replacement") is not None else None

        if target and target not in allowed_targets:
            errors.append(f"{edit_path}.target must be one of: {', '.join(sorted(allowed_targets))}")

        if action and action not in allowed_actions:
            errors.append(f"{edit_path}.action must be one of: {', '.join(sorted(allowed_actions))}")

        if target == "header" and not header_field:
            errors.append(f"{edit_path}.field is required when target is 'header'")

        if target == "start_line" and action == "remove":
            errors.append(f"{edit_path}: action 'remove' is not allowed for start_line")

        parsed.append(
            MessageEdit(
                target=target,
                action=action,
                field=header_field,
                value=message_value,
                pattern=pattern,
                replacement=replacement,
            )
        )

    return parsed


def _parse_intercept_edits(value: Any, field: str, errors: List[str]) -> List[MessageEdit]:
    parsed = _parse_edits(value, field, errors)

    for idx, edit in enumerate(parsed, start=1):
        edit_path = f"{field}[{idx}]"
        target = edit.target.lower()
        action = edit.action.lower()

        if target == "header" and action not in {"set", "remove"}:
            errors.append(f"{edit_path}.action must be set or remove when target is header")

        if target in {"start_line", "body"} and action != "set":
            errors.append(f"{edit_path}.action must be set when target is {target}")

        if action == "set" and edit.value is None:
            errors.append(f"{edit_path}.value is required when action is set")

    return parsed


def _parse_expected_response(value: Mapping[str, Any], field: str, errors: List[str]) -> ExpectedResponse:
    status_code = None
    if "status_code" in value and value.get("status_code") is not None:
        parsed_status = _as_int(value.get("status_code"), f"{field}.status_code", errors)
        status_code = parsed_status if parsed_status > 0 else None

    reason_contains = [str(item) for item in _as_list(value.get("reason_contains", []), f"{field}.reason_contains", errors)]

    header_contains_raw = value.get("header_contains", {})
    header_contains_map = _as_mapping(header_contains_raw, f"{field}.header_contains", errors)
    header_contains = {str(k): str(v) for k, v in header_contains_map.items()}

    header_absent = [str(item) for item in _as_list(value.get("header_absent", []), f"{field}.header_absent", errors)]
    body_contains = [str(item) for item in _as_list(value.get("body_contains", []), f"{field}.body_contains", errors)]

    return ExpectedResponse(
        status_code=status_code,
        reason_contains=reason_contains,
        header_contains=header_contains,
        header_absent=header_absent,
        body_contains=body_contains,
    )
