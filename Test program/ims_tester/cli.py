from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, Mapping, Optional, Sequence

from .adapters import SipProxyHttpTransport, TransportRegistry
from .config import load_runtime_config, load_test_suite
from .editor import BasicSipMessageModifier
from .engine import ComplianceTestRunner, DifferentialTestRunner
from .errors import ConfigValidationError
from .models import ComparisonReport, ComplianceReport, DeviceProfile, RuntimeConfig
from .reporter import render_comparison_report, render_compliance_report, report_to_dict


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ims-tester",
        description="IMS SIP test CLI with interface-first transport and message editing",
    )
    subparsers = parser.add_subparsers(dest="command")

    validate_cmd = subparsers.add_parser("validate", help="Validate a test suite YAML file")
    validate_cmd.add_argument("--test-config", required=True, help="Path to test suite YAML")

    list_devices_cmd = subparsers.add_parser(
        "list-devices",
        help="Show configured devices plus SIP REGISTER-discovered devices",
    )
    list_devices_cmd.add_argument("--runtime-config", required=True, help="Path to runtime YAML")

    run_standard_cmd = subparsers.add_parser(
        "run-standard",
        help="Run expected-response validation against one device",
    )
    run_standard_cmd.add_argument("--test-config", required=True, help="Path to test suite YAML")
    run_standard_cmd.add_argument("--runtime-config", required=True, help="Path to runtime YAML")
    run_standard_cmd.add_argument(
        "--device",
        help="Device ID, phone number, or IP. If omitted, choose from discovered devices.",
    )
    run_standard_cmd.add_argument(
        "--report-json",
        help="Optional path to write machine-readable JSON report",
    )
    run_standard_cmd.add_argument(
        "--no-wait",
        action="store_true",
        help="Do not wait for Enter between test cases",
    )

    compare_cmd = subparsers.add_parser(
        "compare",
        help="Run differential comparison between two devices",
    )
    compare_cmd.add_argument("--test-config", required=True, help="Path to test suite YAML")
    compare_cmd.add_argument("--runtime-config", required=True, help="Path to runtime YAML")
    compare_cmd.add_argument("--device-a", required=True, help="First device ID")
    compare_cmd.add_argument("--device-b", required=True, help="Second device ID")
    compare_cmd.add_argument(
        "--report-json",
        help="Optional path to write machine-readable JSON report",
    )
    compare_cmd.add_argument(
        "--no-wait",
        action="store_true",
        help="Do not wait for Enter between test cases",
    )

    live_edit_list_cmd = subparsers.add_parser(
        "live-edit-list",
        help="List active live edit rules in sip_proxy",
    )
    live_edit_list_cmd.add_argument("--runtime-config", required=True, help="Path to runtime YAML")

    live_edit_clear_cmd = subparsers.add_parser(
        "live-edit-clear",
        help="Clear all active live edit rules in sip_proxy",
    )
    live_edit_clear_cmd.add_argument("--runtime-config", required=True, help="Path to runtime YAML")

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 1

    try:
        if args.command == "validate":
            return _handle_validate(args.test_config)

        if args.command == "list-devices":
            return _handle_list_devices(args.runtime_config)

        if args.command == "run-standard":
            return _handle_run_standard(
                test_config_path=args.test_config,
                runtime_config_path=args.runtime_config,
                device_id=args.device,
                report_json_path=args.report_json,
                wait_for_enter_between_cases=not args.no_wait,
            )

        if args.command == "compare":
            return _handle_compare(
                test_config_path=args.test_config,
                runtime_config_path=args.runtime_config,
                device_a_id=args.device_a,
                device_b_id=args.device_b,
                report_json_path=args.report_json,
                wait_for_enter_between_cases=not args.no_wait,
            )

        if args.command == "live-edit-list":
            return _handle_live_edit_list(args.runtime_config)

        if args.command == "live-edit-clear":
            return _handle_live_edit_clear(args.runtime_config)

        parser.print_help()
        return 1

    except ConfigValidationError as exc:
        print("Configuration errors:")
        for item in exc.errors:
            print(f"- {item}")
        return 2
    except Exception as exc:
        print(f"Unhandled error: {exc}")
        return 1


def _handle_validate(test_config_path: str) -> int:
    suite = load_test_suite(test_config_path)
    print(f"Valid test suite: {suite.suite_id} ({suite.title})")
    print(f"Cases: {len(suite.cases)}")
    return 0


def _handle_list_devices(runtime_config_path: str) -> int:
    runtime = load_runtime_config(runtime_config_path)
    transport = TransportRegistry().create(runtime.transport.name, runtime.transport.settings)

    available_devices: Dict[str, DeviceProfile] = dict(runtime.devices)
    discovered_devices: Dict[str, DeviceProfile] = {}
    discovery_error = ""

    if isinstance(transport, SipProxyHttpTransport):
        try:
            transport.open()
            try:
                available_devices, discovered_devices = _collect_available_devices(runtime, transport)
            finally:
                transport.close()
        except Exception as exc:
            discovery_error = str(exc)

    print(f"Transport: {runtime.transport.name}")

    print("Configured devices:")
    if runtime.devices:
        for device in _sort_devices(runtime.devices):
            print(f"- {_format_device_line(device)} [source=config]")
    else:
        print("- (none)")

    if isinstance(transport, SipProxyHttpTransport):
        print("Discovered from SIP REGISTER:")
        if discovery_error:
            print(f"- unavailable ({discovery_error})")
        elif discovered_devices:
            for device in _sort_devices(discovered_devices):
                print(f"- {_format_device_line(device)} [source=register]")
        else:
            print("- (none yet)")

    print("Available for selection:")
    if available_devices:
        for device in _sort_devices(available_devices):
            print(f"- {_format_device_line(device)}")
    else:
        print("- (none)")

    return 0


def _handle_run_standard(
    test_config_path: str,
    runtime_config_path: str,
    device_id: str | None,
    report_json_path: str | None,
    wait_for_enter_between_cases: bool,
) -> int:
    suite = load_test_suite(test_config_path)
    runtime = load_runtime_config(runtime_config_path)

    transport = TransportRegistry().create(runtime.transport.name, runtime.transport.settings)
    modifier = BasicSipMessageModifier()
    runner = ComplianceTestRunner(transport, modifier)

    transport.open()
    try:
        available_devices, _ = _collect_available_devices(runtime, transport)
        if device_id and device_id.strip():
            device = _resolve_device(available_devices, device_id)
        else:
            device = _prompt_for_device_selection(available_devices)

        report = runner.run(
            suite,
            device,
            wait_for_enter_between_cases=wait_for_enter_between_cases,
        )
    finally:
        transport.close()

    print(render_compliance_report(report))
    if report_json_path:
        _write_report_json(report_json_path, report)

    return 0 if report.success else 10


def _handle_compare(
    test_config_path: str,
    runtime_config_path: str,
    device_a_id: str,
    device_b_id: str,
    report_json_path: str | None,
    wait_for_enter_between_cases: bool,
) -> int:
    suite = load_test_suite(test_config_path)
    runtime = load_runtime_config(runtime_config_path)

    transport = TransportRegistry().create(runtime.transport.name, runtime.transport.settings)
    modifier = BasicSipMessageModifier()
    runner = DifferentialTestRunner(transport, modifier)

    transport.open()
    try:
        available_devices, _ = _collect_available_devices(runtime, transport)
        device_a = _resolve_device(available_devices, device_a_id)
        device_b = _resolve_device(available_devices, device_b_id)

        report = runner.run(
            suite,
            device_a,
            device_b,
            wait_for_enter_between_cases=wait_for_enter_between_cases,
        )
    finally:
        transport.close()

    print(render_comparison_report(report))
    if report_json_path:
        _write_report_json(report_json_path, report)

    return 0 if not report.differences_found else 11


def _resolve_device(available_devices: Mapping[str, DeviceProfile], device_selector: str) -> DeviceProfile:
    device = _find_device(available_devices, device_selector)
    if device is None:
        available = ", ".join(sorted(available_devices.keys()))
        raise ConfigValidationError(
            [
                f"Unknown device '{device_selector}'. Available device IDs: {available or '(none)'}",
                "Tip: omit --device to choose interactively from discovered SIP REGISTER devices.",
            ]
        )
    return device


def _collect_available_devices(
    runtime: RuntimeConfig,
    transport: object,
) -> tuple[Dict[str, DeviceProfile], Dict[str, DeviceProfile]]:
    available_devices: Dict[str, DeviceProfile] = dict(runtime.devices)
    discovered_devices: Dict[str, DeviceProfile] = {}

    if isinstance(transport, SipProxyHttpTransport):
        for discovered in transport.list_discovered_devices():
            discovered_devices[discovered.device_id] = discovered
            available_devices.setdefault(discovered.device_id, discovered)

    return available_devices, discovered_devices


def _sort_devices(devices: Mapping[str, DeviceProfile]) -> list[DeviceProfile]:
    return sorted(devices.values(), key=lambda item: item.device_id.lower())


def _device_phone_number(device: DeviceProfile) -> str:
    value = str(device.metadata.get("phone_number", "")).strip()
    return value


def _device_imsi(device: DeviceProfile) -> str:
    value = str(device.metadata.get("imsi", "")).strip()
    return value


def _device_user_agent(device: DeviceProfile) -> str:
    value = str(device.metadata.get("user_agent", "")).strip()
    return value


def _format_device_line(device: DeviceProfile) -> str:
    phone_number = _device_phone_number(device)
    imsi = _device_imsi(device)
    user_agent = _device_user_agent(device)
    phone_fragment = f", phone={phone_number}" if phone_number else ""
    imsi_fragment = f", imsi={imsi}" if imsi else ""
    user_agent_fragment = f", ua={user_agent}" if user_agent else ""
    return f"{device.device_id}: {device.display_name} ({device.address}{phone_fragment}{imsi_fragment}{user_agent_fragment})"


def _format_device_selection_line(index: int, device: DeviceProfile) -> str:
    phone_number = _device_phone_number(device) or "-"
    imsi = _device_imsi(device) or "-"
    user_agent = _device_user_agent(device) or "-"
    return f"{index}: {phone_number} - {imsi} - {user_agent}"


def _find_device(available_devices: Mapping[str, DeviceProfile], selector: str) -> DeviceProfile | None:
    normalized = selector.strip()
    if not normalized:
        return None

    direct = available_devices.get(normalized)
    if direct is not None:
        return direct

    lowered = normalized.lower()
    for device in available_devices.values():
        if device.display_name.strip().lower() == lowered:
            return device
        if device.address.strip().lower() == lowered:
            return device
        if _device_phone_number(device) == normalized:
            return device
        if _device_imsi(device) == normalized:
            return device

    return None


def _prompt_for_device_selection(available_devices: Mapping[str, DeviceProfile]) -> DeviceProfile:
    ordered = _sort_devices(available_devices)
    if not ordered:
        raise ConfigValidationError(
            [
                "No devices are available.",
                "If using sip-proxy-http, wait for phones to REGISTER then rerun.",
            ]
        )

    if len(ordered) == 1:
        selected = ordered[0]
        print(f"No --device provided. Auto-selected only available device: {_format_device_line(selected)}")
        return selected

    if not sys.stdin.isatty():
        available = ", ".join(device.device_id for device in ordered)
        raise ConfigValidationError(
            [
                "--device is required in non-interactive mode when multiple devices are available.",
                f"Available device IDs: {available}",
            ]
        )

    print("No --device provided. Choose a device:")
    for index, device in enumerate(ordered, start=1):
        print(_format_device_selection_line(index, device))

    while True:
        choice = input("Select by number or device id: ").strip()
        if not choice:
            continue

        if choice.isdigit():
            selected_index = int(choice)
            if 1 <= selected_index <= len(ordered):
                return ordered[selected_index - 1]

        selected = _find_device(available_devices, choice)
        if selected is not None:
            return selected

        print("Invalid selection. Please enter a valid number or device identifier.")


def _resolve_proxy_transport(runtime: RuntimeConfig) -> SipProxyHttpTransport:
    transport = TransportRegistry().create(runtime.transport.name, runtime.transport.settings)
    if not isinstance(transport, SipProxyHttpTransport):
        raise ConfigValidationError(
            [
                "Live editing requires transport 'sip-proxy-http' in runtime config.",
                f"Current transport: {runtime.transport.name}",
            ]
        )
    return transport


def _handle_live_edit_list(runtime_config_path: str) -> int:
    runtime = load_runtime_config(runtime_config_path)
    transport = _resolve_proxy_transport(runtime)

    transport.open()
    try:
        rules = transport.list_live_edit_rules()
    finally:
        transport.close()

    print(json.dumps({"count": len(rules), "rules": rules}, indent=2))
    return 0


def _handle_live_edit_clear(runtime_config_path: str) -> int:
    runtime = load_runtime_config(runtime_config_path)
    transport = _resolve_proxy_transport(runtime)

    transport.open()
    try:
        cleared = transport.clear_live_edit_rules()
    finally:
        transport.close()

    print(json.dumps({"status": "ok", "cleared": cleared}, indent=2))
    return 0


def _write_report_json(path: str, report: ComplianceReport | ComparisonReport) -> None:
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = report_to_dict(report)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"JSON report written: {out_path}")
