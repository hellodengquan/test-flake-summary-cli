"""Test case classifier and statistics aggregator."""

from collections import defaultdict
from typing import Dict, List

from .models import (
    ClassifiedTestCase,
    TestCategory,
    TestCaseStats,
    TestRun,
    TestStatus,
)


class TestCaseClassifier:
    """Classifies test cases into categories and calculates statistics."""

    def __init__(
        self,
        min_runs: int = 3,
        stable_pass_threshold: float = 0.95,
        consecutive_fail_threshold: int = 3,
    ):
        self.min_runs = min_runs
        self.stable_pass_threshold = stable_pass_threshold
        self.consecutive_fail_threshold = consecutive_fail_threshold

    def aggregate_stats(self, test_runs: List[TestRun]) -> Dict[str, TestCaseStats]:
        stats_map: Dict[str, TestCaseStats] = {}

        for run in test_runs:
            for result in run.results:
                key = f"{result.file}::{result.name}"
                if key not in stats_map:
                    stats_map[key] = TestCaseStats(
                        name=result.name,
                        file=result.file,
                        team=result.team,
                    )

                stats = stats_map[key]
                stats.history.append(result.status)

                if result.status == TestStatus.PASSED:
                    stats.passed += 1
                elif result.status == TestStatus.FAILED:
                    stats.failed += 1
                elif result.status == TestStatus.SKIPPED:
                    stats.skipped += 1

        return stats_map

    def classify(
        self, stats_map: Dict[str, TestCaseStats]
    ) -> List[ClassifiedTestCase]:
        classified = []

        for stats in stats_map.values():
            category, flaky_score, consecutive_failures = self._classify_case(stats)
            classified.append(
                ClassifiedTestCase(
                    stats=stats,
                    category=category,
                    flaky_score=flaky_score,
                    recent_consecutive_failures=consecutive_failures,
                )
            )

        return classified

    def _classify_case(
        self, stats: TestCaseStats
    ) -> tuple[TestCategory, float, int]:
        consecutive_failures = self._count_recent_consecutive_failures(stats.history)
        flaky_score = self._calculate_flaky_score(stats)

        if stats.total_runs < self.min_runs:
            if stats.fail_rate > 0:
                return TestCategory.FLAKY, flaky_score, consecutive_failures
            return TestCategory.STABLE_PASS, flaky_score, consecutive_failures

        if consecutive_failures >= self.consecutive_fail_threshold:
            return TestCategory.CONTINUOUS_FAIL, flaky_score, consecutive_failures

        if stats.pass_rate >= self.stable_pass_threshold and stats.failed == 0:
            return TestCategory.STABLE_PASS, flaky_score, consecutive_failures

        if stats.failed > 0 and stats.passed > 0:
            return TestCategory.FLAKY, flaky_score, consecutive_failures

        if stats.failed > 0 and stats.passed == 0:
            return TestCategory.CONTINUOUS_FAIL, flaky_score, consecutive_failures

        return TestCategory.STABLE_PASS, flaky_score, consecutive_failures

    def _count_recent_consecutive_failures(self, history: List[TestStatus]) -> int:
        count = 0
        for status in reversed(history):
            if status == TestStatus.FAILED:
                count += 1
            else:
                break
        return count

    def _calculate_flaky_score(self, stats: TestCaseStats) -> float:
        if stats.total_runs == 0 or stats.failed == 0:
            return 0.0

        non_skipped_runs = stats.passed + stats.failed
        if non_skipped_runs == 0:
            return 0.0

        fail_rate = stats.failed / non_skipped_runs

        history = stats.history
        transitions = 0
        for i in range(1, len(history)):
            prev = history[i - 1]
            curr = history[i]
            if prev != curr and prev != TestStatus.SKIPPED and curr != TestStatus.SKIPPED:
                transitions += 1

        max_transitions = max(non_skipped_runs - 1, 1)
        transition_score = transitions / max_transitions

        recency_factor = self._calculate_recency_factor(history)

        score = (fail_rate * 0.5) + (transition_score * 0.3) + (recency_factor * 0.2)
        return round(min(score * 100, 100.0), 2)

    def _calculate_recency_factor(self, history: List[TestStatus]) -> float:
        recent_failures = 0
        recent_window = min(5, len(history))
        if recent_window == 0:
            return 0.0

        for i in range(1, recent_window + 1):
            if history[-i] == TestStatus.FAILED:
                weight = recent_window - i + 1
                recent_failures += weight

        max_possible = recent_window * (recent_window + 1) // 2
        return recent_failures / max_possible if max_possible > 0 else 0.0
