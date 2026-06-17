"""Test case classifier and statistics aggregator."""

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from .models import (
    ClassifiedTestCase,
    TestCategory,
    TestCaseStats,
    TestRun,
    TestStatus,
)


def _parse_timestamp(timestamp: str) -> Optional[datetime]:
    if not timestamp:
        return None

    ts = timestamp.strip()
    if not ts:
        return None

    ts = ts.replace("Z", "+00:00")

    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        pass

    formats = [
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(ts, fmt)
        except ValueError:
            continue

    iso_week_match = re.match(r"(\d{4})-W(\d{2})-(\d)", ts)
    if iso_week_match:
        year = int(iso_week_match.group(1))
        week = int(iso_week_match.group(2))
        day = int(iso_week_match.group(3))
        try:
            return datetime.fromisocalendar(year, week, day)
        except ValueError:
            pass

    return None


@dataclass
class WeightsConfig:
    """Configuration for flaky score calculation weights."""

    fail_rate_weight: float = 0.5
    transition_weight: float = 0.3
    recency_weight: float = 0.2
    recency_window_size: int = 5

    @classmethod
    def from_dict(cls, data: Dict) -> "WeightsConfig":
        return cls(
            fail_rate_weight=data.get("fail_rate_weight", 0.5),
            transition_weight=data.get("transition_weight", 0.3),
            recency_weight=data.get("recency_weight", 0.2),
            recency_window_size=data.get("recency_window_size", 5),
        )

    @classmethod
    def from_file(cls, file_path: str) -> "WeightsConfig":
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)

    def validate(self, auto_normalize: bool = False) -> None:
        if self.fail_rate_weight < 0 or self.transition_weight < 0 or self.recency_weight < 0:
            raise ValueError("All weights must be non-negative")
        if self.recency_window_size < 1:
            raise ValueError("recency_window_size must be >= 1")

        total = self.fail_rate_weight + self.transition_weight + self.recency_weight
        if total == 0:
            raise ValueError("Sum of weights must be greater than 0")

        if auto_normalize and abs(total - 1.0) > 0.001:
            self.fail_rate_weight /= total
            self.transition_weight /= total
            self.recency_weight /= total
        elif abs(total - 1.0) > 0.001:
            raise ValueError(
                f"Weight sum must equal 1.0, got {total:.4f}. "
                "Set auto_normalize=True to auto-normalize."
            )

    def normalize(self) -> None:
        total = self.fail_rate_weight + self.transition_weight + self.recency_weight
        if total == 0:
            raise ValueError("Cannot normalize: sum of weights is zero")
        if abs(total - 1.0) > 0.001:
            self.fail_rate_weight /= total
            self.transition_weight /= total
            self.recency_weight /= total


class TestCaseClassifier:
    """Classifies test cases into categories and calculates statistics."""

    def __init__(
        self,
        min_runs: int = 3,
        stable_pass_threshold: float = 0.95,
        fail_ratio_threshold: float = 0.7,
        weights: Optional[WeightsConfig] = None,
        time_window_days: Optional[int] = None,
        auto_normalize_weights: bool = True,
    ):
        self.min_runs = min_runs
        self.stable_pass_threshold = stable_pass_threshold
        self.fail_ratio_threshold = fail_ratio_threshold
        self.weights = weights or WeightsConfig()
        self.weights.validate(auto_normalize=auto_normalize_weights)
        self.time_window_days = time_window_days

    def filter_runs_by_time_window(self, test_runs: List[TestRun]) -> List[TestRun]:
        if self.time_window_days is None:
            return test_runs

        cutoff_date = datetime.now() - timedelta(days=self.time_window_days)
        filtered = []

        for run in test_runs:
            run_date = _parse_timestamp(run.timestamp)
            if run_date is None:
                filtered.append(run)
                continue

            if run_date.tzinfo is not None and cutoff_date.tzinfo is None:
                run_date = run_date.replace(tzinfo=None)
            elif run_date.tzinfo is None and cutoff_date.tzinfo is not None:
                cutoff_date = cutoff_date.replace(tzinfo=None)

            if run_date >= cutoff_date:
                filtered.append(run)

        return filtered

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
            if stats.total_runs < self.min_runs:
                continue

            category, flaky_score, fail_ratio = self._classify_case(stats)
            classified.append(
                ClassifiedTestCase(
                    stats=stats,
                    category=category,
                    flaky_score=flaky_score,
                    recent_consecutive_failures=int(fail_ratio * 100),
                )
            )

        return classified

    def _classify_case(
        self, stats: TestCaseStats
    ) -> tuple[TestCategory, float, float]:
        total = stats.total_runs
        if total == 0:
            return TestCategory.STABLE_PASS, 0.0, 0.0

        fail_ratio = stats.failed / total if total > 0 else 0.0
        flaky_score = self._calculate_flaky_score(stats)

        if stats.failed > 0 and stats.passed == 0:
            return TestCategory.CONTINUOUS_FAIL, flaky_score, fail_ratio

        if fail_ratio >= self.fail_ratio_threshold:
            return TestCategory.CONTINUOUS_FAIL, flaky_score, fail_ratio

        if stats.pass_rate >= self.stable_pass_threshold and stats.failed == 0:
            return TestCategory.STABLE_PASS, flaky_score, fail_ratio

        if stats.failed > 0 and stats.passed > 0:
            return TestCategory.FLAKY, flaky_score, fail_ratio

        return TestCategory.STABLE_PASS, flaky_score, fail_ratio

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

        w = self.weights
        score = (
            (fail_rate * w.fail_rate_weight)
            + (transition_score * w.transition_weight)
            + (recency_factor * w.recency_weight)
        )
        return round(min(score * 100, 100.0), 2)

    def _calculate_recency_factor(self, history: List[TestStatus]) -> float:
        recent_failures = 0
        recent_window = min(self.weights.recency_window_size, len(history))
        if recent_window == 0:
            return 0.0

        for i in range(1, recent_window + 1):
            if history[-i] == TestStatus.FAILED:
                weight = recent_window - i + 1
                recent_failures += weight

        max_possible = recent_window * (recent_window + 1) // 2
        return recent_failures / max_possible if max_possible > 0 else 0.0
