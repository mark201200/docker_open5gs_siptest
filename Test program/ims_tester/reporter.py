from __future__ import annotations

from dataclasses import asdict
import re
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
    device_line = " vs ".join(report.device_ids or [report.device_a, report.device_b])
    lines = [
        f"Suite: {report.suite_id} ({report.suite_title})",
        f"Comparison: {device_line}",
        f"Result: {report.cases_with_differences}/{report.total_cases} cases with differences",
        f"Window: {report.started_at_utc} -> {report.finished_at_utc}",
        "",
    ]

    for case_index, case in enumerate(report.case_results):
        if case_index > 0:
            lines.append("")

        label = "DIFF" if case.differences_found else "MATCH"
        lines.append(f"[{label}] {case.case_id} - {case.description}")
        for iteration_index, iteration in enumerate(case.iterations):
            if iteration_index > 0:
                lines.append("")

            i_label = "DIFF" if iteration.differences else "MATCH"
            lines.append(f"  Iteration {iteration.iteration}: {i_label}")
            for item in iteration.differences:
                lines.extend(_format_comparison_difference(item))

    return "\n".join(lines)


def _format_comparison_difference(item: str) -> list[str]:
    header_match = re.match(r"^header '(.+?)' differs: A=(.+), B=(.+)$", item)
    if header_match is None:
        return [f"    - {item}"]

    header_name, value_a, value_b = header_match.groups()
    return [
        f"    - header '{header_name}' differs:",
        f"        A={value_a}",
        f"        B={value_b}",
        "",
    ]
