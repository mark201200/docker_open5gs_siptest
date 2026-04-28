from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class DeviceProfile:
    device_id: str
    display_name: str
    address: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MessageEdit:
    target: str
    action: str
    field: Optional[str] = None
    value: Optional[str] = None
    pattern: Optional[str] = None
    replacement: Optional[str] = None


@dataclass(frozen=True)
class RepeatPolicy:
    count: int = 1
    rate_per_second: float = 1.0


@dataclass(frozen=True)
class MessageSpec:
    message_type: str
    template: str
    edits: List[MessageEdit] = field(default_factory=list)
    intercept_edits: List[MessageEdit] = field(default_factory=list)
    intercept_only: bool = False
    intercept_message_type: str = "*"
    intercept_direction: str = "request"
    intercept_wait_timeout_seconds: float = 30.0
    repeat: RepeatPolicy = field(default_factory=RepeatPolicy)


@dataclass(frozen=True)
class ExpectedResponse:
    status_code: Optional[int] = None
    reason_contains: List[str] = field(default_factory=list)
    header_contains: Dict[str, str] = field(default_factory=dict)
    header_absent: List[str] = field(default_factory=list)
    body_contains: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class TestCase:
    case_id: str
    description: str
    message: MessageSpec
    expected_response: ExpectedResponse
    timeout_seconds: Optional[float] = None


@dataclass(frozen=True)
class TestSuite:
    suite_id: str
    title: str
    default_timeout_seconds: float
    cases: List[TestCase]


@dataclass(frozen=True)
class RuntimeTransportConfig:
    name: str
    settings: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RuntimeConfig:
    transport: RuntimeTransportConfig
    devices: Dict[str, DeviceProfile]


@dataclass(frozen=True)
class SipResponse:
    raw_message: str
    status_code: int
    reason_phrase: str
    headers: Dict[str, List[str]]
    body: str

    @staticmethod
    def parse(raw_message: str) -> "SipResponse":
        normalized = raw_message.replace("\r\n", "\n")
        head, _, body = normalized.partition("\n\n")
        lines = [line for line in head.split("\n") if line.strip()]
        if not lines:
            return SipResponse(raw_message=raw_message, status_code=0, reason_phrase="", headers={}, body=body)

        start_line = lines[0].strip()
        parts = start_line.split(" ", 2)
        if len(parts) < 3:
            return SipResponse(raw_message=raw_message, status_code=0, reason_phrase="", headers={}, body=body)

        status_code = int(parts[1]) if parts[1].isdigit() else 0
        reason_phrase = parts[2].strip()

        headers: Dict[str, List[str]] = {}
        for line in lines[1:]:
            if ":" not in line:
                continue
            name, value = line.split(":", 1)
            key = name.strip().lower()
            headers.setdefault(key, []).append(value.strip())

        return SipResponse(
            raw_message=raw_message,
            status_code=status_code,
            reason_phrase=reason_phrase,
            headers=headers,
            body=body,
        )

    def header_values(self, name: str) -> List[str]:
        return self.headers.get(name.lower(), [])


@dataclass(frozen=True)
class IterationResult:
    iteration: int
    passed: bool
    mismatches: List[str]
    sent_message: str
    responses: List[SipResponse]


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    description: str
    passed: bool
    iterations: List[IterationResult]


@dataclass(frozen=True)
class ComplianceReport:
    suite_id: str
    suite_title: str
    device_id: str
    started_at_utc: str
    finished_at_utc: str
    total_cases: int
    passed_cases: int
    case_results: List[CaseResult]

    @property
    def success(self) -> bool:
        return self.total_cases == self.passed_cases


@dataclass(frozen=True)
class ComparisonIteration:
    iteration: int
    differences: List[str]
    response_a: Optional[SipResponse]
    response_b: Optional[SipResponse]


@dataclass(frozen=True)
class ComparisonCaseResult:
    case_id: str
    description: str
    differences_found: bool
    iterations: List[ComparisonIteration]


@dataclass(frozen=True)
class ComparisonReport:
    suite_id: str
    suite_title: str
    device_a: str
    device_b: str
    started_at_utc: str
    finished_at_utc: str
    total_cases: int
    cases_with_differences: int
    case_results: List[ComparisonCaseResult]

    @property
    def differences_found(self) -> bool:
        return self.cases_with_differences > 0


def utc_now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
