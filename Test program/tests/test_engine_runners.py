from __future__ import annotations

import pytest

from ims_tester.adapters import StubSipTransport
from ims_tester.editor import BasicSipMessageModifier
from ims_tester.engine import ComplianceTestRunner, DifferentialTestRunner
from ims_tester.models import (
    ExpectedResponse,
    DeviceProfile,
    MessageEdit,
    MessageSpec,
    RepeatPolicy,
    TestCase as ModelTestCase,
    TestSuite as ModelTestSuite,
)


def _suite_with_single_case(*, expected_status: int, repeat: RepeatPolicy | None = None) -> ModelTestSuite:
    repeat_policy = repeat or RepeatPolicy(count=1, rate_per_second=1.0)
    case = ModelTestCase(
        case_id="c1",
        description="case",
        message=MessageSpec(
            message_type="REGISTER",
            template="REGISTER sip:x SIP/2.0\r\n\r\n",
            edits=[],
            intercept_edits=[],
            intercept_only=False,
            repeat=repeat_policy,
        ),
        expected_response=ExpectedResponse(status_code=expected_status),
    )
    return ModelTestSuite(suite_id="s1", title="suite", default_timeout_seconds=1.0, cases=[case])


def test_compliance_runner_passes_when_expected_matches(device_pixel) -> None:
    transport = StubSipTransport({"canned_responses": {"REGISTER": "SIP/2.0 200 OK\r\n\r\n"}})
    modifier = BasicSipMessageModifier()
    runner = ComplianceTestRunner(transport, modifier)

    suite = _suite_with_single_case(expected_status=200)

    transport.open()
    try:
        report = runner.run(suite, device_pixel)
    finally:
        transport.close()

    assert report.success is True
    assert report.passed_cases == 1
    assert report.total_cases == 1


def test_compliance_runner_records_mismatch_on_failure(device_pixel) -> None:
    transport = StubSipTransport({"canned_responses": {"REGISTER": "SIP/2.0 404 Not Found\r\n\r\n"}})
    runner = ComplianceTestRunner(transport, BasicSipMessageModifier())

    suite = _suite_with_single_case(expected_status=200)

    transport.open()
    try:
        report = runner.run(suite, device_pixel)
    finally:
        transport.close()

    assert report.success is False
    assert report.case_results[0].passed is False
    mismatches = report.case_results[0].iterations[0].mismatches
    assert any("status_code mismatch" in item for item in mismatches)


def test_compliance_runner_sleeps_between_repeated_iterations(monkeypatch, device_pixel) -> None:
    slept = []

    def fake_sleep(value: float) -> None:
        slept.append(value)

    monkeypatch.setattr("ims_tester.engine.time.sleep", fake_sleep)

    transport = StubSipTransport({"canned_responses": {"REGISTER": "SIP/2.0 200 OK\r\n\r\n"}})
    runner = ComplianceTestRunner(transport, BasicSipMessageModifier())

    suite = _suite_with_single_case(expected_status=200, repeat=RepeatPolicy(count=3, rate_per_second=2.0))

    transport.open()
    try:
        report = runner.run(suite, device_pixel)
    finally:
        transport.close()

    assert report.success is True
    assert len(slept) == 2
    assert all(value == pytest.approx(0.5) for value in slept)


def test_compliance_runner_waits_between_cases_by_default(monkeypatch, device_pixel) -> None:
    prompts = []

    def fake_input(prompt: str = "") -> str:
        prompts.append(prompt)
        return ""

    monkeypatch.setattr("builtins.input", fake_input)

    transport = StubSipTransport({"canned_responses": {"REGISTER": "SIP/2.0 200 OK\r\n\r\n"}})
    runner = ComplianceTestRunner(transport, BasicSipMessageModifier())

    case_a = ModelTestCase(
        case_id="c1",
        description="case a",
        message=MessageSpec(
            message_type="REGISTER",
            template="REGISTER sip:x SIP/2.0\r\n\r\n",
            repeat=RepeatPolicy(count=1, rate_per_second=1.0),
        ),
        expected_response=ExpectedResponse(status_code=200),
    )
    case_b = ModelTestCase(
        case_id="c2",
        description="case b",
        message=MessageSpec(
            message_type="REGISTER",
            template="REGISTER sip:y SIP/2.0\r\n\r\n",
            repeat=RepeatPolicy(count=1, rate_per_second=1.0),
        ),
        expected_response=ExpectedResponse(status_code=200),
    )
    suite = ModelTestSuite(
        suite_id="s1",
        title="suite",
        default_timeout_seconds=1.0,
        cases=[case_a, case_b],
    )

    transport.open()
    try:
        report = runner.run(suite, device_pixel)
    finally:
        transport.close()

    assert report.success is True
    assert len(prompts) == 1
    assert "Press Enter to start next test" in prompts[0]


def test_compliance_runner_no_wait_option_skips_case_pause(monkeypatch, device_pixel) -> None:
    def fail_input(prompt: str = "") -> str:  # pragma: no cover
        raise AssertionError("input() should not be called when waiting is disabled")

    monkeypatch.setattr("builtins.input", fail_input)

    transport = StubSipTransport({"canned_responses": {"REGISTER": "SIP/2.0 200 OK\r\n\r\n"}})
    runner = ComplianceTestRunner(transport, BasicSipMessageModifier())

    case_a = ModelTestCase(
        case_id="c1",
        description="case a",
        message=MessageSpec(
            message_type="REGISTER",
            template="REGISTER sip:x SIP/2.0\r\n\r\n",
            repeat=RepeatPolicy(count=1, rate_per_second=1.0),
        ),
        expected_response=ExpectedResponse(status_code=200),
    )
    case_b = ModelTestCase(
        case_id="c2",
        description="case b",
        message=MessageSpec(
            message_type="REGISTER",
            template="REGISTER sip:y SIP/2.0\r\n\r\n",
            repeat=RepeatPolicy(count=1, rate_per_second=1.0),
        ),
        expected_response=ExpectedResponse(status_code=200),
    )
    suite = ModelTestSuite(
        suite_id="s1",
        title="suite",
        default_timeout_seconds=1.0,
        cases=[case_a, case_b],
    )

    transport.open()
    try:
        report = runner.run(suite, device_pixel, wait_for_enter_between_cases=False)
    finally:
        transport.close()

    assert report.success is True


class _FakeLiveEditTransport:
    def __init__(self, wait_results):
        self.wait_results = list(wait_results)
        self.replaced_rules = []
        self._opened = False

    def open(self) -> None:
        self._opened = True

    def close(self) -> None:
        self._opened = False

    def send(self, device, raw_message, context):  # pragma: no cover
        raise AssertionError("send() should not be called for intercept_only cases")

    def read(self, device, correlation_id, timeout_seconds):  # pragma: no cover
        raise AssertionError("read() should not be called for intercept_only cases")

    def replace_live_edit_rules(self, rules):
        self.replaced_rules = list(rules)
        return self.replaced_rules

    def wait_for_live_edit_match(self, rule_ids, timeout_seconds, method="*", direction="any"):
        if self.wait_results:
            return dict(self.wait_results.pop(0))
        return {"matched": False}


def test_intercept_only_case_passes_when_wait_matches(device_pixel) -> None:
    transport = _FakeLiveEditTransport(
        wait_results=[
            {"matched": True, "matched_method": "INVITE", "matched_direction": "request"},
            {"matched": True, "matched_method": "INVITE", "matched_direction": "request"},
        ]
    )
    runner = ComplianceTestRunner(transport, BasicSipMessageModifier())

    case = ModelTestCase(
        case_id="c1",
        description="",
        message=MessageSpec(
            message_type="INVITE",
            template="",
            intercept_only=True,
            intercept_edits=[MessageEdit(target="header", action="set", field="X-Test", value="1")],
            repeat=RepeatPolicy(count=2, rate_per_second=10.0),
            intercept_wait_timeout_seconds=0.1,
        ),
        expected_response=ExpectedResponse(),
    )

    suite = ModelTestSuite(suite_id="s1", title="", default_timeout_seconds=1.0, cases=[case])

    transport.open()
    try:
        report = runner.run(suite, device_pixel)
    finally:
        transport.close()

    assert report.success is True
    assert report.case_results[0].passed is True


def test_intercept_only_case_fails_when_wait_times_out(device_pixel) -> None:
    transport = _FakeLiveEditTransport(wait_results=[{"matched": False}])
    runner = ComplianceTestRunner(transport, BasicSipMessageModifier())

    case = ModelTestCase(
        case_id="c1",
        description="",
        message=MessageSpec(
            message_type="INVITE",
            template="",
            intercept_only=True,
            intercept_edits=[MessageEdit(target="header", action="set", field="X-Test", value="1")],
            repeat=RepeatPolicy(count=1, rate_per_second=1.0),
            intercept_wait_timeout_seconds=0.1,
        ),
        expected_response=ExpectedResponse(),
    )

    suite = ModelTestSuite(suite_id="s1", title="", default_timeout_seconds=1.0, cases=[case])

    transport.open()
    try:
        report = runner.run(suite, device_pixel)
    finally:
        transport.close()

    assert report.success is False
    mismatches = report.case_results[0].iterations[0].mismatches
    assert any("No matching live SIP message observed" in item for item in mismatches)


def test_differential_runner_reports_differences(device_pixel, device_galaxy) -> None:
    transport = StubSipTransport(
        {
            "canned_responses": {
                device_pixel.device_id: {"REGISTER": "SIP/2.0 200 OK\r\n\r\n"},
                device_galaxy.device_id: {"REGISTER": "SIP/2.0 404 Not Found\r\n\r\n"},
            }
        }
    )
    runner = DifferentialTestRunner(transport, BasicSipMessageModifier())

    case = ModelTestCase(
        case_id="c1",
        description="",
        message=MessageSpec(
            message_type="REGISTER",
            template="REGISTER sip:x SIP/2.0\r\n\r\n",
            repeat=RepeatPolicy(count=1, rate_per_second=1.0),
        ),
        expected_response=ExpectedResponse(),
    )

    suite = ModelTestSuite(suite_id="s1", title="", default_timeout_seconds=1.0, cases=[case])

    transport.open()
    try:
        report = runner.run(suite, device_pixel, device_galaxy)
    finally:
        transport.close()

    assert report.differences_found is True
    assert report.cases_with_differences == 1
    assert report.device_ids == [device_pixel.device_id, device_galaxy.device_id]
    diffs = report.case_results[0].iterations[0].differences
    assert any("status_code differs" in item for item in diffs)


def test_differential_runner_supports_three_devices(device_pixel, device_galaxy) -> None:
    device_tablet = DeviceProfile(
        device_id="device_tablet",
        display_name="Tablet",
        address="10.0.0.3",
        metadata={},
    )
    transport = StubSipTransport(
        {
            "canned_responses": {
                device_pixel.device_id: {"REGISTER": "SIP/2.0 200 OK\r\n\r\n"},
                device_galaxy.device_id: {"REGISTER": "SIP/2.0 404 Not Found\r\n\r\n"},
                device_tablet.device_id: {"REGISTER": "SIP/2.0 200 OK\r\n\r\n"},
            }
        }
    )
    runner = DifferentialTestRunner(transport, BasicSipMessageModifier())

    case = ModelTestCase(
        case_id="c1",
        description="",
        message=MessageSpec(
            message_type="REGISTER",
            template="REGISTER sip:x SIP/2.0\r\n\r\n",
            repeat=RepeatPolicy(count=1, rate_per_second=1.0),
        ),
        expected_response=ExpectedResponse(),
    )

    suite = ModelTestSuite(suite_id="s1", title="", default_timeout_seconds=1.0, cases=[case])

    transport.open()
    try:
        report = runner.run(suite, device_pixel, device_galaxy, device_tablet)
    finally:
        transport.close()

    assert report.device_ids == [device_pixel.device_id, device_galaxy.device_id, device_tablet.device_id]
    iteration = report.case_results[0].iterations[0]
    assert set(iteration.responses_by_device) == {
        device_pixel.device_id,
        device_galaxy.device_id,
        device_tablet.device_id,
    }
    assert any("status_code differs" in item for item in iteration.differences)


def test_differential_runner_normalizes_header_order_and_body_whitespace(device_pixel, device_galaxy) -> None:
    transport = StubSipTransport(
        {
            "canned_responses": {
                device_pixel.device_id: {
                    "REGISTER": "SIP/2.0 200 OK\r\nX-Test: alpha\r\nX-Order: one\r\n\r\nLine1\r\nLine2\r\n",
                },
                device_galaxy.device_id: {
                    "REGISTER": "SIP/2.0 200 OK\r\nX-Order: one\r\nx-test: alpha \r\n\r\nLine1\nLine2  \n",
                },
            }
        }
    )
    runner = DifferentialTestRunner(transport, BasicSipMessageModifier())

    case = ModelTestCase(
        case_id="c1",
        description="",
        message=MessageSpec(
            message_type="REGISTER",
            template="REGISTER sip:x SIP/2.0\r\n\r\n",
            repeat=RepeatPolicy(count=1, rate_per_second=1.0),
        ),
        expected_response=ExpectedResponse(),
    )

    suite = ModelTestSuite(suite_id="s1", title="", default_timeout_seconds=1.0, cases=[case])

    transport.open()
    try:
        report = runner.run(suite, device_pixel, device_galaxy)
    finally:
        transport.close()

    assert report.differences_found is False
    assert report.case_results[0].iterations[0].differences == []
