from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, Union

from .models import ComparisonReport, ComplianceReport


def report_to_dict(report: Union[ComplianceReport, ComparisonReport]) -> Dict[str, Any]:
    return asdict(report)


def render_compliance_report(report: ComplianceReport) -> str:
    lines = [
        f"Suite: {report.suite_id} ({report.suite_title})",
        f"Device: {report.device_id}",
        f"Result: {report.passed_cases}/{report.total_cases} cases passed",
        f"Window: {report.started_at_utc} -> {report.finished_at_utc}",
        "",
    ]

    for case in report.case_results:
        label = "PASS" if case.passed else "FAIL"
        lines.append(f"[{label}] {case.case_id} - {case.description}")
        for iteration in case.iterations:
            i_label = "PASS" if iteration.passed else "FAIL"
            lines.append(f"  Iteration {iteration.iteration}: {i_label}")
            if not iteration.passed:
                for mismatch in iteration.mismatches:
                    lines.append(f"    - {mismatch}")

    return "\n".join(lines)


def render_comparison_report(report: ComparisonReport) -> str:
    lines = [
        f"Suite: {report.suite_id} ({report.suite_title})",
        f"Comparison: {report.device_a} vs {report.device_b}",
        f"Result: {report.cases_with_differences}/{report.total_cases} cases with differences",
        f"Window: {report.started_at_utc} -> {report.finished_at_utc}",
        "",
    ]

    for case in report.case_results:
        label = "DIFF" if case.differences_found else "MATCH"
        lines.append(f"[{label}] {case.case_id} - {case.description}")
        for iteration in case.iterations:
            i_label = "DIFF" if iteration.differences else "MATCH"
            lines.append(f"  Iteration {iteration.iteration}: {i_label}")
            for item in iteration.differences:
                lines.append(f"    - {item}")

    return "\n".join(lines)
