from __future__ import annotations

import builtins
import json
from pathlib import Path
import textwrap
from types import SimpleNamespace

import pytest

import ims_tester.cli as cli
from ims_tester.errors import ConfigValidationError
from ims_tester.models import (
    CaseResult,
    ComplianceReport,
    DeviceProfile,
    IterationResult,
    SipResponse,
)


def _yaml(value: str) -> str:
    return textwrap.dedent(value).strip() + "\n"


def test_main_without_command_prints_help_and_returns_1(capsys) -> None:
    code = cli.main([])
    assert code == 1

    captured = capsys.readouterr()
    assert "ims-tester" in captured.out


def test_validate_command_success(tmp_path: Path, capsys) -> None:
    suite_path = tmp_path / "suite.yaml"
    suite_path.write_text(
        _yaml(
            """
            suite:
              id: demo

            tests:
              - id: c1
                message:
                  type: REGISTER
                  template: hi
            """
        ),
        encoding="utf-8",
    )

    code = cli.main(["validate", "--test-config", str(suite_path)])
    assert code == 0

    out = capsys.readouterr().out
    assert "Valid test suite: demo" in out


def test_validate_command_invalid_config_returns_2(tmp_path: Path, capsys) -> None:
    suite_path = tmp_path / "suite.yaml"
    suite_path.write_text(
        _yaml(
            """
            suite:
              title: no id

            tests:
              - id: c1
                message:
                  type: REGISTER
                  template: hi
            """
        ),
        encoding="utf-8",
    )

    code = cli.main(["validate", "--test-config", str(suite_path)])
    assert code == 2

    out = capsys.readouterr().out
    assert "Configuration errors:" in out
    assert "suite.id is required" in out


def test_prompt_for_device_selection_auto_selects_single_device(capsys, device_pixel) -> None:
    selected = cli._prompt_for_device_selection({device_pixel.device_id: device_pixel})
    assert selected.device_id == device_pixel.device_id

    out = capsys.readouterr().out
    assert "Auto-selected" in out


def test_prompt_for_device_selection_non_tty_requires_device(monkeypatch, device_pixel, device_galaxy) -> None:
    class _DummyStdin:
        def __init__(self, is_tty: bool):
            self._is_tty = is_tty

        def isatty(self) -> bool:
            return self._is_tty

    monkeypatch.setattr(cli.sys, "stdin", _DummyStdin(False))

    with pytest.raises(ConfigValidationError):
        cli._prompt_for_device_selection(
            {
                device_pixel.device_id: device_pixel,
                device_galaxy.device_id: device_galaxy,
            }
        )


def test_prompt_for_device_selection_interactive_by_number(monkeypatch, device_pixel, device_galaxy) -> None:
    class _DummyStdin:
        def isatty(self) -> bool:
            return True

    monkeypatch.setattr(cli.sys, "stdin", _DummyStdin())

    # Sorted order: galaxy_s24 then pixel_8
    inputs = iter(["2"])
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(inputs))

    selected = cli._prompt_for_device_selection(
        {
            device_pixel.device_id: device_pixel,
            device_galaxy.device_id: device_galaxy,
        }
    )
    assert selected.device_id == "pixel_8"


def test_prompt_for_device_selection_interactive_by_id(monkeypatch, device_pixel, device_galaxy) -> None:
    class _DummyStdin:
        def isatty(self) -> bool:
            return True

    monkeypatch.setattr(cli.sys, "stdin", _DummyStdin())

    inputs = iter(["galaxy_s24"])
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(inputs))

    selected = cli._prompt_for_device_selection(
        {
            device_pixel.device_id: device_pixel,
            device_galaxy.device_id: device_galaxy,
        }
    )
    assert selected.device_id == "galaxy_s24"


def test_prompt_for_device_selection_interactive_multi_select_by_number(monkeypatch, device_pixel, device_galaxy) -> None:
    class _DummyStdin:
        def isatty(self) -> bool:
            return True

    monkeypatch.setattr(cli.sys, "stdin", _DummyStdin())

    inputs = iter(["1,2"])
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(inputs))

    selected = cli._prompt_for_multiple_device_selection(
        {
            device_pixel.device_id: device_pixel,
            device_galaxy.device_id: device_galaxy,
        },
        minimum_count=1,
    )

    assert [device.device_id for device in selected] == ["galaxy_s24", "pixel_8"]


def test_write_report_json_writes_machine_readable_json(tmp_path: Path, capsys) -> None:
    report_path = tmp_path / "out" / "report.json"

    response = SipResponse.parse("SIP/2.0 200 OK\r\n\r\n")
    report = ComplianceReport(
        suite_id="s1",
        suite_title="Suite",
        device_id="d1",
        started_at_utc="2026-01-01T00:00:00Z",
        finished_at_utc="2026-01-01T00:00:01Z",
        total_cases=1,
        passed_cases=1,
        case_results=[
            CaseResult(
                case_id="c1",
                description="desc",
                passed=True,
                iterations=[
                    IterationResult(
                        iteration=1,
                        passed=True,
                        mismatches=[],
                        sent_message="",
                        responses=[response],
                    )
                ],
            )
        ],
    )

    cli._write_report_json(str(report_path), report)

    assert report_path.exists()
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["suite_id"] == "s1"

    out = capsys.readouterr().out
    assert "JSON report written" in out


def test_find_device_matches_display_name_and_address() -> None:
    devices = {
        "d1": DeviceProfile(device_id="d1", display_name="Pixel", address="10.0.0.1", metadata={}),
        "d2": DeviceProfile(device_id="d2", display_name="Galaxy", address="10.0.0.2", metadata={}),
    }

    assert cli._find_device(devices, "d1").device_id == "d1"
    assert cli._find_device(devices, "pixel").device_id == "d1"
    assert cli._find_device(devices, "10.0.0.2").device_id == "d2"


def test_run_standard_parser_accepts_no_wait() -> None:
    parser = cli.build_parser()
    args = parser.parse_args(
        [
            "run-standard",
            "--test-config",
            "suite.yaml",
            "--runtime-config",
            "runtime.yaml",
            "--no-wait",
        ]
    )
    assert args.no_wait is True


def test_compare_parser_accepts_no_wait() -> None:
    parser = cli.build_parser()
    args = parser.parse_args(
        [
            "compare",
            "--test-config",
            "suite.yaml",
            "--runtime-config",
            "runtime.yaml",
            "--device",
            "a",
            "--device",
            "b",
            "--no-wait",
        ]
    )
    assert args.no_wait is True
    assert args.devices == ["a", "b"]


def test_resolve_devices_for_compare_accepts_multiple_selectors(device_pixel, device_galaxy) -> None:
    devices = cli._resolve_devices_for_compare(
        {
            device_pixel.device_id: device_pixel,
            device_galaxy.device_id: device_galaxy,
        },
        [device_pixel.device_id, device_galaxy.device_id],
    )

    assert [device.device_id for device in devices] == [device_pixel.device_id, device_galaxy.device_id]


def test_run_standard_without_device_can_run_multiple_selected_devices(
    monkeypatch,
    capsys,
    device_pixel,
    device_galaxy,
) -> None:
    class _DummyStdin:
        def isatty(self) -> bool:
            return True

    class _DummyTransport:
        def open(self) -> None:
            return None

        def close(self) -> None:
            return None

    class _DummyRegistry:
        def create(self, name: str, settings: dict[str, object]) -> _DummyTransport:
            return _DummyTransport()

    class _DummyRunner:
        def __init__(self, transport: object, modifier: object) -> None:
            self.calls: list[str] = []

        def run(self, suite, device, *, wait_for_enter_between_cases: bool = True):
            self.calls.append(device.device_id)
            return SimpleNamespace(
                success=True,
                device_id=device.device_id,
                suite_id=suite.suite_id,
                suite_title=suite.title,
                started_at_utc="2026-01-01T00:00:00Z",
                finished_at_utc="2026-01-01T00:00:01Z",
                passed_cases=1,
                total_cases=1,
                case_results=[],
            )

    class _DummyDiffRunner:
        def __init__(self, transport: object, modifier: object) -> None:
            self.calls: list[list[str]] = []

        def run(self, suite, *devices, wait_for_enter_between_cases: bool = True):
            self.calls.append([device.device_id for device in devices])
            return SimpleNamespace(
                differences_found=False,
                device_a=devices[0].device_id,
                device_b=devices[1].device_id,
                device_ids=[device.device_id for device in devices],
                suite_id=suite.suite_id,
                suite_title=suite.title,
                started_at_utc="2026-01-01T00:00:00Z",
                finished_at_utc="2026-01-01T00:00:01Z",
                total_cases=0,
                cases_with_differences=0,
                case_results=[],
            )

    monkeypatch.setattr(cli.sys, "stdin", _DummyStdin())
    monkeypatch.setattr(builtins, "input", lambda prompt="": "1,2")
    monkeypatch.setattr(cli, "TransportRegistry", lambda: _DummyRegistry())
    monkeypatch.setattr(cli, "BasicSipMessageModifier", lambda: object())
    monkeypatch.setattr(cli, "ComplianceTestRunner", _DummyRunner)
    monkeypatch.setattr(cli, "DifferentialTestRunner", _DummyDiffRunner)
    monkeypatch.setattr(
        cli,
        "render_comparison_report",
        lambda report: f"comparison:{' vs '.join(report.device_ids)}",
    )

    suite = SimpleNamespace(suite_id="demo", title="Demo", cases=[], default_timeout_seconds=1.0)
    runtime = SimpleNamespace(
        transport=SimpleNamespace(name="stub", settings={}),
        devices={
            device_pixel.device_id: device_pixel,
            device_galaxy.device_id: device_galaxy,
        },
    )

    monkeypatch.setattr(cli, "load_test_suite", lambda path: suite)
    monkeypatch.setattr(cli, "load_runtime_config", lambda path: runtime)

    code = cli._handle_run_standard(
        test_config_path="suite.yaml",
        runtime_config_path="runtime.yaml",
        device_id=None,
        report_json_path=None,
        wait_for_enter_between_cases=False,
    )

    assert code == 0
    out = capsys.readouterr().out
    assert "Running differential comparison instead of run-standard" in out
    assert "comparison:galaxy_s24 vs pixel_8" in out
