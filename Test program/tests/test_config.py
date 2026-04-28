from __future__ import annotations

from pathlib import Path
import textwrap

import pytest

from ims_tester.config import load_runtime_config, load_test_suite
from ims_tester.errors import ConfigValidationError


def _yaml(value: str) -> str:
  return textwrap.dedent(value).strip() + "\n"


def test_load_test_suite_minimal_valid(tmp_path: Path) -> None:
    path = tmp_path / "suite.yaml"
    path.write_text(
        _yaml(
            """
            suite:
              id: demo
              title: Demo Suite

            tests:
              - id: register_ok
                description: basic
                message:
                  type: REGISTER
                  template: |
                    REGISTER sip:ims.example SIP/2.0

                expected_response:
                  status_code: 200
            """
        ),
        encoding="utf-8",
    )

    suite = load_test_suite(path)
    assert suite.suite_id == "demo"
    assert suite.title == "Demo Suite"
    assert suite.default_timeout_seconds == 3.0
    assert len(suite.cases) == 1
    assert suite.cases[0].case_id == "register_ok"
    assert suite.cases[0].message.message_type == "REGISTER"


def test_load_test_suite_missing_suite_id_is_validation_error(tmp_path: Path) -> None:
    path = tmp_path / "suite.yaml"
    path.write_text(
        _yaml(
            """
            suite:
              title: Missing ID
            tests:
              - id: c1
                message:
                  type: REGISTER
                  template: hi
            """
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigValidationError) as excinfo:
        load_test_suite(path)

    assert any("suite.id is required" in e for e in excinfo.value.errors)


def test_load_test_suite_duplicate_case_ids_error(tmp_path: Path) -> None:
    path = tmp_path / "suite.yaml"
    path.write_text(
        _yaml(
            """
            suite:
              id: demo

            tests:
              - id: dup
                message:
                  type: REGISTER
                  template: hi
              - id: dup
                message:
                  type: REGISTER
                  template: hi
            """
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigValidationError) as excinfo:
        load_test_suite(path)

    assert any("Duplicate case id 'dup'" in e for e in excinfo.value.errors)


def test_load_test_suite_validates_repeat_policy(tmp_path: Path) -> None:
    path = tmp_path / "suite.yaml"
    path.write_text(
        _yaml(
            """
            suite:
              id: demo

            tests:
              - id: c1
                message:
                  type: REGISTER
                  template: hi
                  repeat:
                    count: 0
                    rate_per_second: 0
            """
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigValidationError) as excinfo:
        load_test_suite(path)

    errors = "\n".join(excinfo.value.errors)
    assert "tests[1].message.repeat.count must be >= 1" in errors
    assert "tests[1].message.repeat.rate_per_second must be > 0" in errors


def test_load_test_suite_validates_edits_and_intercept_only_constraints(tmp_path: Path) -> None:
    path = tmp_path / "suite.yaml"
    path.write_text(
        _yaml(
            """
            suite:
              id: demo

            tests:
              - id: c1
                message:
                  type: INVITE
                  intercept_only: true
                  intercept_edits: []
                  edits:
                    - target: header
                      action: set
                      value: abc
                    - target: start_line
                      action: remove
            """
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigValidationError) as excinfo:
        load_test_suite(path)

    errors = "\n".join(excinfo.value.errors)
    assert "tests[1].message.intercept_edits must define at least one intercept edit" in errors
    assert "tests[1].message.edits[1].field is required when target is 'header'" in errors
    assert "tests[1].message.edits[2]: action 'remove' is not allowed for start_line" in errors


def test_load_test_suite_validates_intercept_edit_restrictions(tmp_path: Path) -> None:
    path = tmp_path / "suite.yaml"
    path.write_text(
        _yaml(
            """
            suite:
              id: demo

            tests:
              - id: c1
                message:
                  type: INVITE
                  intercept_only: true
                  intercept_edits:
                    - target: header
                      action: append
                      field: X-Test
                      value: nope
                    - target: start_line
                      action: corrupt
                      value: BAD
                    - target: body
                      action: set
            """
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigValidationError) as excinfo:
        load_test_suite(path)

    errors = "\n".join(excinfo.value.errors)
    assert "tests[1].message.intercept_edits[1].action must be set or remove when target is header" in errors
    assert "tests[1].message.intercept_edits[2].action must be set when target is start_line" in errors
    assert "tests[1].message.intercept_edits[3].value is required when action is set" in errors


def test_load_test_suite_yaml_shape_errors(tmp_path: Path) -> None:
    missing = tmp_path / "missing.yaml"
    with pytest.raises(ConfigValidationError) as excinfo:
        load_test_suite(missing)
    assert any("File not found" in e for e in excinfo.value.errors)

    path = tmp_path / "suite_list.yaml"
    path.write_text("- item\n", encoding="utf-8")
    with pytest.raises(ConfigValidationError) as excinfo2:
        load_test_suite(path)
    assert any("Top-level YAML document must be a mapping" in e for e in excinfo2.value.errors)


def test_load_runtime_config_minimal_valid(tmp_path: Path) -> None:
    path = tmp_path / "runtime.yaml"
    path.write_text(
        _yaml(
            """
            transport:
              name: stub
              settings:
                default_status: 200

            devices:
              - id: pixel_8
                name: Pixel
                address: 10.0.0.10
                metadata:
                  phone_number: "15551234567"
            """
        ),
        encoding="utf-8",
    )

    runtime = load_runtime_config(path)
    assert runtime.transport.name == "stub"
    assert runtime.transport.settings["default_status"] == 200
    assert "pixel_8" in runtime.devices
    assert runtime.devices["pixel_8"].metadata["phone_number"] == "15551234567"


def test_load_runtime_config_allows_no_devices_for_sip_proxy_http(tmp_path: Path) -> None:
    path = tmp_path / "runtime.yaml"
    path.write_text(
        _yaml(
            """
            transport:
              name: sip-proxy-http
              settings:
                api_base_url: http://localhost:8080
            devices: []
            """
        ),
        encoding="utf-8",
    )

    runtime = load_runtime_config(path)
    assert runtime.transport.name == "sip-proxy-http"
    assert runtime.devices == {}


def test_load_runtime_config_validates_shapes_and_duplicates(tmp_path: Path) -> None:
    path = tmp_path / "runtime.yaml"
    path.write_text(
        _yaml(
            """
            transport:
              name: stub
              settings: not-a-map

            devices:
              - id: dev
                address: 10.0.0.1
                metadata: []
              - id: dev
                address: 10.0.0.2
            """
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigValidationError) as excinfo:
        load_runtime_config(path)

    errors = "\n".join(excinfo.value.errors)
    assert "transport.settings must be a mapping" in errors
    assert "devices[1].metadata must be a mapping" in errors
    assert "Duplicate device id 'dev' in runtime config" in errors
