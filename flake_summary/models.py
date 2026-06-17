"""Core data models for test flake summary."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class TestStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


class TestCategory(str, Enum):
    STABLE_PASS = "stable_pass"
    FLAKY = "flaky"
    CONTINUOUS_FAIL = "continuous_fail"


@dataclass
class TestResult:
    name: str
    status: TestStatus
    file: str
    team: str = "unknown"
    duration: float = 0.0
    message: Optional[str] = None


@dataclass
class TestRun:
    run_id: str
    timestamp: str
    results: List[TestResult] = field(default_factory=list)


@dataclass
class TestCaseStats:
    name: str
    file: str
    team: str
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    history: List[TestStatus] = field(default_factory=list)

    @property
    def total_runs(self) -> int:
        return self.passed + self.failed + self.skipped

    @property
    def pass_rate(self) -> float:
        if self.total_runs == 0:
            return 0.0
        return self.passed / self.total_runs

    @property
    def fail_rate(self) -> float:
        if self.total_runs == 0:
            return 0.0
        return self.failed / self.total_runs


@dataclass
class ClassifiedTestCase:
    stats: TestCaseStats
    category: TestCategory
    flaky_score: float
    recent_consecutive_failures: int = 0


@dataclass
class TeamSummary:
    team: str
    total_tests: int
    flaky_tests: int
    continuous_fail_tests: int
    stable_pass_tests: int
    avg_flaky_score: float


@dataclass
class FileSummary:
    file: str
    team: str
    total_tests: int
    flaky_tests: int
    continuous_fail_tests: int
    stable_pass_tests: int
    avg_flaky_score: float


@dataclass
class SummaryReport:
    total_runs: int
    total_test_cases: int
    categories: Dict[TestCategory, int]
    classified_tests: List[ClassifiedTestCase]
    team_summaries: List[TeamSummary]
    file_summaries: List[FileSummary]
    overall_flaky_rate: float
