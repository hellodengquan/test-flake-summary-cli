"""Team and file grouping summary generator."""

from collections import defaultdict
from typing import Dict, List

from .models import (
    ClassifiedTestCase,
    FileSummary,
    SkippedTestCase,
    SummaryReport,
    TeamSummary,
    TestCategory,
    TestRun,
)
from .classifier import TestCaseClassifier


class SummaryGenerator:
    """Generates summary reports grouped by team and file."""

    def __init__(self, classifier: TestCaseClassifier = None):
        self.classifier = classifier or TestCaseClassifier()

    def generate_report(self, test_runs: List[TestRun]) -> SummaryReport:
        filtered_runs = self.classifier.filter_runs_by_time_window(test_runs)
        stats_map = self.classifier.aggregate_stats(filtered_runs)
        classified_tests, skipped_tests = self.classifier.classify(stats_map)

        categories: Dict[TestCategory, int] = defaultdict(int)
        for ct in classified_tests:
            categories[ct.category] += 1

        team_summaries = self._group_by_team(classified_tests)
        file_summaries = self._group_by_file(classified_tests)

        total_tests = len(classified_tests)
        flaky_count = categories.get(TestCategory.FLAKY, 0)
        overall_flaky_rate = flaky_count / total_tests if total_tests > 0 else 0.0

        return SummaryReport(
            total_runs=len(filtered_runs),
            total_test_cases=total_tests,
            categories=dict(categories),
            classified_tests=classified_tests,
            team_summaries=team_summaries,
            file_summaries=file_summaries,
            overall_flaky_rate=round(overall_flaky_rate * 100, 2),
            skipped_tests=skipped_tests,
        )

    def _group_by_team(
        self, classified_tests: List[ClassifiedTestCase]
    ) -> List[TeamSummary]:
        team_data: Dict[str, Dict] = defaultdict(
            lambda: {
                "total": 0,
                "flaky": 0,
                "continuous_fail": 0,
                "stable_pass": 0,
                "flaky_scores": [],
            }
        )

        for ct in classified_tests:
            team = ct.stats.team
            data = team_data[team]
            data["total"] += 1
            data["flaky_scores"].append(ct.flaky_score)

            if ct.category == TestCategory.FLAKY:
                data["flaky"] += 1
            elif ct.category == TestCategory.CONTINUOUS_FAIL:
                data["continuous_fail"] += 1
            elif ct.category == TestCategory.STABLE_PASS:
                data["stable_pass"] += 1

        summaries = []
        for team, data in sorted(team_data.items()):
            avg_score = (
                round(sum(data["flaky_scores"]) / len(data["flaky_scores"]), 2)
                if data["flaky_scores"]
                else 0.0
            )
            summaries.append(
                TeamSummary(
                    team=team,
                    total_tests=data["total"],
                    flaky_tests=data["flaky"],
                    continuous_fail_tests=data["continuous_fail"],
                    stable_pass_tests=data["stable_pass"],
                    avg_flaky_score=avg_score,
                )
            )

        return summaries

    def _group_by_file(
        self, classified_tests: List[ClassifiedTestCase]
    ) -> List[FileSummary]:
        file_data: Dict[str, Dict] = defaultdict(
            lambda: {
                "team": "unknown",
                "total": 0,
                "flaky": 0,
                "continuous_fail": 0,
                "stable_pass": 0,
                "flaky_scores": [],
            }
        )

        for ct in classified_tests:
            file_key = ct.stats.file
            data = file_data[file_key]
            data["team"] = ct.stats.team
            data["total"] += 1
            data["flaky_scores"].append(ct.flaky_score)

            if ct.category == TestCategory.FLAKY:
                data["flaky"] += 1
            elif ct.category == TestCategory.CONTINUOUS_FAIL:
                data["continuous_fail"] += 1
            elif ct.category == TestCategory.STABLE_PASS:
                data["stable_pass"] += 1

        summaries = []
        for file_key, data in sorted(file_data.items()):
            avg_score = (
                round(sum(data["flaky_scores"]) / len(data["flaky_scores"]), 2)
                if data["flaky_scores"]
                else 0.0
            )
            summaries.append(
                FileSummary(
                    file=file_key,
                    team=data["team"],
                    total_tests=data["total"],
                    flaky_tests=data["flaky"],
                    continuous_fail_tests=data["continuous_fail"],
                    stable_pass_tests=data["stable_pass"],
                    avg_flaky_score=avg_score,
                )
            )

        return summaries
