from __future__ import annotations

from ims_tester.models import (
    CaseResult,
    ComparisonCaseResult,
    ComparisonIteration,
    ComparisonReport,
    ComplianceReport,
    IterationResult,
    SipResponse,
)
from ims_tester.reporter import render_comparison_report, render_compliance_report, report_to_dict


def test_render_compliance_report_includes_pass_fail_lines() -> None:
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

    text = render_compliance_report(report)
    assert "Suite: s1 (Suite)" in text
    assert "Device: d1" in text
    assert "Result: 1/1 cases passed" in text
    assert "[PASS] c1 - desc" in text

    payload = report_to_dict(report)
    assert payload["suite_id"] == "s1"


def test_render_comparison_report_includes_differences() -> None:
    report = ComparisonReport(
        suite_id="s1",
        suite_title="Suite",
        device_a="a",
        device_b="b",
        started_at_utc="2026-01-01T00:00:00Z",
        finished_at_utc="2026-01-01T00:00:01Z",
        total_cases=1,
        cases_with_differences=1,
        case_results=[
            ComparisonCaseResult(
                case_id="c1",
                description="desc",
                differences_found=True,
                iterations=[
                    ComparisonIteration(
                        iteration=1,
                        differences=["status_code differs"],
                        response_a=None,
                        response_b=None,
                    )
                ],
            )
        ],
    )

    text = render_comparison_report(report)
    assert "Comparison: a vs b" in text
    assert "[DIFF] c1 - desc" in text
    assert "- status_code differs" in text
