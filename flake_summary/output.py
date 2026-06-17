"""Output formatter for text table and JSON formats."""

import json
from dataclasses import asdict
from typing import List

from . import __version__
from .models import (
    ClassifiedTestCase,
    FileSummary,
    SkippedTestCase,
    SummaryReport,
    TeamSummary,
    TestCategory,
    TestStatus,
)


class OutputFormatter:
    """Formats summary reports for output."""

    SCHEMA_VERSION = "1.1.0"

    @staticmethod
    def format_json(report: SummaryReport, indent: int = 2) -> str:
        data = {
            "schema_version": OutputFormatter.SCHEMA_VERSION,
            "tool_version": __version__,
            "total_runs": report.total_runs,
            "total_test_cases": report.total_test_cases,
            "overall_flaky_rate": report.overall_flaky_rate,
            "categories": {k.value: v for k, v in report.categories.items()},
            "classified_tests": [
                OutputFormatter._test_case_to_dict(ct)
                for ct in sorted(
                    report.classified_tests,
                    key=lambda x: (-x.flaky_score, x.stats.name),
                )
            ],
            "skipped_tests": [
                OutputFormatter._skipped_test_to_dict(st)
                for st in report.skipped_tests
            ],
            "team_summaries": [asdict(ts) for ts in report.team_summaries],
            "file_summaries": [asdict(fs) for fs in report.file_summaries],
        }
        return json.dumps(data, indent=indent, ensure_ascii=False)

    @staticmethod
    def _test_case_to_dict(ct: ClassifiedTestCase) -> dict:
        return {
            "name": ct.stats.name,
            "file": ct.stats.file,
            "team": ct.stats.team,
            "category": ct.category.value,
            "flaky_score": ct.flaky_score,
            "passed": ct.stats.passed,
            "failed": ct.stats.failed,
            "skipped": ct.stats.skipped,
            "total_runs": ct.stats.total_runs,
            "pass_rate": round(ct.stats.pass_rate * 100, 2),
            "fail_rate": round(ct.stats.fail_rate * 100, 2),
            "fail_ratio_pct": ct.recent_consecutive_failures,
            "history": [h.value for h in ct.stats.history],
        }

    @staticmethod
    def _skipped_test_to_dict(st: SkippedTestCase) -> dict:
        return {
            "name": st.name,
            "file": st.file,
            "team": st.team,
            "total_runs": st.total_runs,
            "min_runs_required": st.min_runs_required,
            "passed": st.passed,
            "failed": st.failed,
            "skipped_count": st.skipped,
            "reason": st.reason,
        }

    @staticmethod
    def format_text_table(
        report: SummaryReport,
        show_all: bool = False,
        show_only_flaky: bool = False,
    ) -> str:
        lines = []

        lines.append("=" * 100)
        lines.append("TEST FLAKE SUMMARY REPORT")
        lines.append("=" * 100)
        lines.append(f"Total CI Runs Analyzed: {report.total_runs}")
        lines.append(f"Total Test Cases: {report.total_test_cases}")
        lines.append(f"Overall Flaky Rate: {report.overall_flaky_rate}%")
        lines.append("")

        lines.append("Category Summary:")
        lines.append("-" * 40)
        for category, count in sorted(report.categories.items()):
            lines.append(f"  {category.value:<25} {count}")
        lines.append("")

        lines.append("-" * 100)
        lines.append("BY TEAM SUMMARY")
        lines.append("-" * 100)
        lines.append(OutputFormatter._format_team_table(report.team_summaries))
        lines.append("")

        lines.append("-" * 100)
        lines.append("BY FILE SUMMARY")
        lines.append("-" * 100)
        lines.append(OutputFormatter._format_file_table(report.file_summaries))
        lines.append("")

        tests_to_show = OutputFormatter._filter_tests(
            report.classified_tests, show_all, show_only_flaky
        )

        if tests_to_show:
            lines.append("-" * 100)
            lines.append("TEST CASE DETAILS")
            lines.append("-" * 100)
            lines.append(OutputFormatter._format_test_case_table(tests_to_show))
        else:
            lines.append("No test cases to display.")

        lines.append("=" * 100)

        return "\n".join(lines)

    @staticmethod
    def _filter_tests(
        tests: List[ClassifiedTestCase],
        show_all: bool,
        show_only_flaky: bool,
    ) -> List[ClassifiedTestCase]:
        sorted_tests = sorted(
            tests,
            key=lambda x: (-x.flaky_score, x.stats.name),
        )

        if show_only_flaky:
            return [t for t in sorted_tests if t.category == TestCategory.FLAKY]

        if show_all:
            return sorted_tests

        return [t for t in sorted_tests if t.category != TestCategory.STABLE_PASS]

    @staticmethod
    def _format_team_table(summaries: List[TeamSummary]) -> str:
        if not summaries:
            return "No team data available."

        header = f"{'Team':<25} {'Total':>6} {'Flaky':>6} {'Fail':>6} {'Stable':>8} {'Avg Score':>10}"
        separator = "-" * len(header)
        lines = [header, separator]

        for s in summaries:
            lines.append(
                f"{s.team:<25} {s.total_tests:>6} {s.flaky_tests:>6} "
                f"{s.continuous_fail_tests:>6} {s.stable_pass_tests:>8} "
                f"{s.avg_flaky_score:>9.2f}"
            )

        return "\n".join(lines)

    @staticmethod
    def _format_file_table(summaries: List[FileSummary]) -> str:
        if not summaries:
            return "No file data available."

        header = f"{'File':<45} {'Team':<15} {'Total':>5} {'Flaky':>5} {'Fail':>5} {'Stable':>7} {'Avg Score':>10}"
        separator = "-" * len(header)
        lines = [header, separator]

        for s in summaries:
            file_display = s.file if len(s.file) <= 42 else "..." + s.file[-42:]
            lines.append(
                f"{file_display:<45} {s.team:<15} {s.total_tests:>5} "
                f"{s.flaky_tests:>5} {s.continuous_fail_tests:>5} "
                f"{s.stable_pass_tests:>7} {s.avg_flaky_score:>9.2f}"
            )

        return "\n".join(lines)

    @staticmethod
    def _format_test_case_table(tests: List[ClassifiedTestCase]) -> str:
        if not tests:
            return "No test cases to display."

        header = (
            f"{'Test Name':<50} {'Category':<16} {'Score':>6} "
            f"{'P/F/S':>9} {'Pass%':>7} {'Fail%':>7} {'History':<15}"
        )
        separator = "-" * len(header)
        lines = [header, separator]

        for ct in tests:
            name_display = ct.stats.name
            if len(name_display) > 47:
                name_display = name_display[:44] + "..."

            category_display = OutputFormatter._get_category_display(ct.category)
            pfs_display = f"{ct.stats.passed}/{ct.stats.failed}/{ct.stats.skipped}"
            pass_rate_display = f"{ct.stats.pass_rate * 100:>5.1f}%"
            fail_rate_display = f"{ct.stats.fail_rate * 100:>5.1f}%"
            history_display = OutputFormatter._format_history(ct.stats.history)

            lines.append(
                f"{name_display:<50} {category_display:<16} "
                f"{ct.flaky_score:>5.1f} {pfs_display:>9} "
                f"{pass_rate_display:>7} {fail_rate_display:>7} {history_display:<15}"
            )

        return "\n".join(lines)

    @staticmethod
    def _get_category_display(category: TestCategory) -> str:
        mapping = {
            TestCategory.STABLE_PASS: "STABLE_PASS",
            TestCategory.FLAKY: "FLAKY",
            TestCategory.CONTINUOUS_FAIL: "CONTINUOUS_FAIL",
        }
        return mapping.get(category, category.value)

    @staticmethod
    def _format_history(history: List[TestStatus]) -> str:
        recent = history[-10:] if len(history) > 10 else history
        symbols = []
        for s in recent:
            if s == TestStatus.PASSED:
                symbols.append(".")
            elif s == TestStatus.FAILED:
                symbols.append("F")
            elif s == TestStatus.SKIPPED:
                symbols.append("S")
        return "".join(symbols)
