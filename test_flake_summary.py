"""Unit tests for flake summary tool."""

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from typing import List

from flake_summary.classifier import TestCaseClassifier, WeightsConfig
from flake_summary.models import (
    TestCategory,
    TestResult,
    TestRun,
    TestStatus,
)
from flake_summary.output import OutputFormatter
from flake_summary.parser import HTTPConfig, TestResultParser
from flake_summary.summarizer import SummaryGenerator


class TestModels(unittest.TestCase):
    """Test data models."""

    def test_test_case_stats_calculations(self):
        from flake_summary.models import TestCaseStats

        stats = TestCaseStats(
            name="test_example",
            file="test_file.py",
            team="test-team",
            passed=7,
            failed=2,
            skipped=1,
        )

        self.assertEqual(stats.total_runs, 10)
        self.assertAlmostEqual(stats.pass_rate, 0.7)
        self.assertAlmostEqual(stats.fail_rate, 0.2)

    def test_test_case_stats_zero_runs(self):
        from flake_summary.models import TestCaseStats

        stats = TestCaseStats(
            name="test_example",
            file="test_file.py",
            team="test-team",
        )

        self.assertEqual(stats.total_runs, 0)
        self.assertEqual(stats.pass_rate, 0.0)
        self.assertEqual(stats.fail_rate, 0.0)


class TestHTTPConfig(unittest.TestCase):
    """Test HTTP configuration."""

    def test_http_config_defaults(self):
        config = HTTPConfig()
        self.assertIsNone(config.basic_auth)
        self.assertIsNone(config.bearer_token)
        self.assertIsNone(config.proxy)
        self.assertFalse(config.has_auth())

    def test_http_config_basic_auth(self):
        config = HTTPConfig(
            basic_auth={"username": "user", "password": "pass"}
        )
        self.assertTrue(config.has_auth())
        self.assertEqual(config.basic_auth["username"], "user")
        self.assertEqual(config.basic_auth["password"], "pass")

    def test_http_config_bearer_token(self):
        config = HTTPConfig(bearer_token="my-secret-token")
        self.assertTrue(config.has_auth())
        self.assertEqual(config.bearer_token, "my-secret-token")

    def test_http_config_proxy(self):
        config = HTTPConfig(proxy={"http": "http://proxy:8080", "https": "http://proxy:8080"})
        self.assertTrue(config.has_auth())
        self.assertIn("http", config.proxy)

    def test_http_config_custom_headers(self):
        config = HTTPConfig(custom_headers={"X-Custom": "value"})
        self.assertIn("X-Custom", config.custom_headers)
        self.assertEqual(config.custom_headers["X-Custom"], "value")


class TestWeightsConfig(unittest.TestCase):
    """Test weights configuration."""

    def test_weights_config_defaults(self):
        weights = WeightsConfig()
        self.assertEqual(weights.fail_rate_weight, 0.5)
        self.assertEqual(weights.transition_weight, 0.3)
        self.assertEqual(weights.recency_weight, 0.2)
        self.assertEqual(weights.recency_window_size, 5)

    def test_weights_config_from_dict(self):
        data = {
            "fail_rate_weight": 0.6,
            "transition_weight": 0.2,
            "recency_weight": 0.2,
            "recency_window_size": 7,
        }
        weights = WeightsConfig.from_dict(data)
        self.assertEqual(weights.fail_rate_weight, 0.6)
        self.assertEqual(weights.recency_window_size, 7)

    def test_weights_config_validate_valid(self):
        weights = WeightsConfig()
        weights.validate()

    def test_weights_config_validate_invalid_sum(self):
        weights = WeightsConfig(
            fail_rate_weight=0.5,
            transition_weight=0.5,
            recency_weight=0.5,
        )
        with self.assertRaises(ValueError):
            weights.validate()

    def test_weights_config_validate_invalid_window(self):
        weights = WeightsConfig(recency_window_size=0)
        with self.assertRaises(ValueError):
            weights.validate()

    def test_weights_config_from_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({
                "fail_rate_weight": 0.4,
                "transition_weight": 0.4,
                "recency_weight": 0.2,
                "recency_window_size": 3,
            }, f)
            temp_file = f.name

        try:
            weights = WeightsConfig.from_file(temp_file)
            self.assertEqual(weights.fail_rate_weight, 0.4)
            self.assertEqual(weights.recency_window_size, 3)
        finally:
            os.unlink(temp_file)


class TestParser(unittest.TestCase):
    """Test result parser."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_parse_junit_xml(self):
        xml_content = '''<?xml version="1.0" encoding="UTF-8"?>
<testsuites name="Test" tests="3" failures="1" errors="0" skipped="1" timestamp="2026-06-10T10:00:00">
  <testsuite name="suite1" tests="3" failures="1" errors="0" skipped="1">
    <testcase name="test_pass" classname="TestClass" file="test_file.py" team="team-a" time="0.1"/>
    <testcase name="test_fail" classname="TestClass" file="test_file.py" team="team-a" time="0.2">
      <failure message="Assertion failed"/>
    </testcase>
    <testcase name="test_skip" classname="TestClass" file="test_file.py" team="team-a" time="0.0">
      <skipped message="Not ready"/>
    </testcase>
  </testsuite>
</testsuites>'''

        file_path = os.path.join(self.temp_dir, "test.xml")
        with open(file_path, "w") as f:
            f.write(xml_content)

        test_run = TestResultParser.parse_file(file_path)

        self.assertEqual(test_run.run_id, "test.xml")
        self.assertEqual(len(test_run.results), 3)

        result_dict = {r.name: r for r in test_run.results}
        self.assertEqual(result_dict["TestClass.test_pass"].status, TestStatus.PASSED)
        self.assertEqual(result_dict["TestClass.test_fail"].status, TestStatus.FAILED)
        self.assertEqual(result_dict["TestClass.test_skip"].status, TestStatus.SKIPPED)

    def test_parse_json(self):
        json_content = json.dumps({
            "timestamp": "2026-06-10T10:00:00",
            "results": [
                {
                    "name": "test_json_pass",
                    "status": "passed",
                    "file": "test_json.py",
                    "team": "team-b",
                    "duration": 0.15,
                },
                {
                    "name": "test_json_fail",
                    "status": "failed",
                    "file": "test_json.py",
                    "team": "team-b",
                    "duration": 0.25,
                    "message": "Error occurred",
                },
            ],
        })

        file_path = os.path.join(self.temp_dir, "test.json")
        with open(file_path, "w") as f:
            f.write(json_content)

        test_run = TestResultParser.parse_file(file_path)

        self.assertEqual(len(test_run.results), 2)
        self.assertEqual(test_run.results[0].status, TestStatus.PASSED)
        self.assertEqual(test_run.results[1].status, TestStatus.FAILED)
        self.assertEqual(test_run.results[1].message, "Error occurred")

    def test_parse_directory(self):
        for i in range(3):
            xml_content = f'''<?xml version="1.0"?>
<testsuites tests="1" failures="0" timestamp="2026-06-10T10:00:0{i}">
  <testsuite tests="1" failures="0">
    <testcase name="test_{i}" classname="Test" file="test.py" team="team" time="0.1"/>
  </testsuite>
</testsuites>'''
            file_path = os.path.join(self.temp_dir, f"run_{i:03d}.xml")
            with open(file_path, "w") as f:
                f.write(xml_content)

        runs = TestResultParser.parse_directory(self.temp_dir)
        self.assertEqual(len(runs), 3)

    def test_parse_invalid_json_no_results(self):
        json_content = json.dumps({
            "not_results": [],
        })
        file_path = os.path.join(self.temp_dir, "invalid.json")
        with open(file_path, "w") as f:
            f.write(json_content)

        with self.assertRaises(ValueError):
            TestResultParser.parse_file(file_path)


class TestClassifier(unittest.TestCase):
    """Test case classifier."""

    def setUp(self):
        self.classifier = TestCaseClassifier(
            min_runs=3,
            stable_pass_threshold=0.95,
            fail_ratio_threshold=0.7,
        )

    def _create_test_runs(self, test_name: str, statuses: List[TestStatus]) -> List[TestRun]:
        runs = []
        for i, status in enumerate(statuses):
            run = TestRun(
                run_id=f"run_{i:03d}",
                timestamp=f"2026-06-{10+i:02d}T10:00:00",
                results=[
                    TestResult(
                        name=test_name,
                        status=status,
                        file="test_file.py",
                        team="test-team",
                    )
                ],
            )
            runs.append(run)
        return runs

    def test_stable_pass(self):
        statuses = [TestStatus.PASSED] * 5
        runs = self._create_test_runs("test_stable", statuses)
        stats_map = self.classifier.aggregate_stats(runs)
        classified = self.classifier.classify(stats_map)

        self.assertEqual(len(classified), 1)
        self.assertEqual(classified[0].category, TestCategory.STABLE_PASS)
        self.assertEqual(classified[0].flaky_score, 0.0)

    def test_flaky_test(self):
        statuses = [
            TestStatus.PASSED,
            TestStatus.FAILED,
            TestStatus.PASSED,
            TestStatus.FAILED,
            TestStatus.PASSED,
        ]
        runs = self._create_test_runs("test_flaky", statuses)
        stats_map = self.classifier.aggregate_stats(runs)
        classified = self.classifier.classify(stats_map)

        self.assertEqual(len(classified), 1)
        self.assertEqual(classified[0].category, TestCategory.FLAKY)
        self.assertGreater(classified[0].flaky_score, 0)

    def test_continuous_fail_by_ratio(self):
        statuses = [
            TestStatus.PASSED,
            TestStatus.FAILED,
            TestStatus.FAILED,
            TestStatus.FAILED,
            TestStatus.FAILED,
        ]
        runs = self._create_test_runs("test_continuous_fail", statuses)
        stats_map = self.classifier.aggregate_stats(runs)
        classified = self.classifier.classify(stats_map)

        self.assertEqual(len(classified), 1)
        self.assertEqual(classified[0].category, TestCategory.CONTINUOUS_FAIL)
        self.assertEqual(classified[0].stats.fail_rate, 0.8)

    def test_fail_ratio_threshold(self):
        classifier = TestCaseClassifier(fail_ratio_threshold=0.5)
        statuses = [
            TestStatus.PASSED,
            TestStatus.PASSED,
            TestStatus.FAILED,
            TestStatus.FAILED,
            TestStatus.FAILED,
        ]
        runs = self._create_test_runs("test_ratio", statuses)
        stats_map = classifier.aggregate_stats(runs)
        classified = classifier.classify(stats_map)

        self.assertEqual(classified[0].category, TestCategory.CONTINUOUS_FAIL)

    def test_all_failed(self):
        statuses = [TestStatus.FAILED] * 5
        runs = self._create_test_runs("test_all_fail", statuses)
        stats_map = self.classifier.aggregate_stats(runs)
        classified = self.classifier.classify(stats_map)

        self.assertEqual(classified[0].category, TestCategory.CONTINUOUS_FAIL)
        self.assertEqual(classified[0].stats.fail_rate, 1.0)

    def test_insufficient_runs(self):
        statuses = [TestStatus.FAILED, TestStatus.PASSED]
        runs = self._create_test_runs("test_insufficient", statuses)
        stats_map = self.classifier.aggregate_stats(runs)
        classified = self.classifier.classify(stats_map)

        self.assertEqual(classified[0].category, TestCategory.FLAKY)

    def test_flaky_score_calculation(self):
        statuses = [
            TestStatus.PASSED,
            TestStatus.PASSED,
            TestStatus.FAILED,
            TestStatus.PASSED,
            TestStatus.FAILED,
        ]
        runs = self._create_test_runs("test_score", statuses)
        stats_map = self.classifier.aggregate_stats(runs)
        stats = stats_map["test_file.py::test_score"]

        score = self.classifier._calculate_flaky_score(stats)
        self.assertGreater(score, 0)
        self.assertLessEqual(score, 100)

    def test_flaky_score_with_custom_weights(self):
        weights = WeightsConfig(
            fail_rate_weight=0.8,
            transition_weight=0.1,
            recency_weight=0.1,
        )
        classifier = TestCaseClassifier(weights=weights)

        statuses = [
            TestStatus.PASSED,
            TestStatus.FAILED,
            TestStatus.PASSED,
            TestStatus.FAILED,
            TestStatus.PASSED,
        ]
        runs = self._create_test_runs("test_custom_weights", statuses)
        stats_map = classifier.aggregate_stats(runs)
        stats = stats_map["test_file.py::test_custom_weights"]

        score = classifier._calculate_flaky_score(stats)
        self.assertGreater(score, 0)
        self.assertLessEqual(score, 100)

    def test_consecutive_failures_with_skipped(self):
        statuses = [
            TestStatus.PASSED,
            TestStatus.FAILED,
            TestStatus.SKIPPED,
            TestStatus.FAILED,
            TestStatus.FAILED,
        ]
        runs = self._create_test_runs("test_skipped", statuses)
        stats_map = self.classifier.aggregate_stats(runs)
        classified = self.classifier.classify(stats_map)

        self.assertEqual(classified[0].stats.fail_rate, 0.6)
        self.assertEqual(classified[0].recent_consecutive_failures, 60)

    def test_time_window_filtering(self):
        old_date = (datetime.now() - timedelta(days=60)).isoformat()
        new_date = (datetime.now() - timedelta(days=5)).isoformat()

        runs = [
            TestRun(
                run_id="old_run",
                timestamp=old_date,
                results=[TestResult(
                    name="test_tw",
                    status=TestStatus.FAILED,
                    file="test.py",
                    team="team",
                )],
            ),
            TestRun(
                run_id="new_run",
                timestamp=new_date,
                results=[TestResult(
                    name="test_tw",
                    status=TestStatus.PASSED,
                    file="test.py",
                    team="team",
                )],
            ),
        ]

        classifier = TestCaseClassifier(time_window_days=30)
        filtered = classifier.filter_runs_by_time_window(runs)

        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0].run_id, "new_run")

    def test_time_window_none(self):
        runs = self._create_test_runs("test", [TestStatus.PASSED] * 3)
        classifier = TestCaseClassifier(time_window_days=None)
        filtered = classifier.filter_runs_by_time_window(runs)
        self.assertEqual(len(filtered), 3)


class TestSummarizer(unittest.TestCase):
    """Summary generator tests."""

    def test_team_and_file_grouping(self):
        runs = [
            TestRun(
                run_id="run_001",
                timestamp="2026-06-10T10:00:00",
                results=[
                    TestResult(
                        name="test1",
                        status=TestStatus.PASSED,
                        file="file1.py",
                        team="team-a",
                    ),
                    TestResult(
                        name="test2",
                        status=TestStatus.FAILED,
                        file="file2.py",
                        team="team-b",
                    ),
                ],
            ),
            TestRun(
                run_id="run_002",
                timestamp="2026-06-11T10:00:00",
                results=[
                    TestResult(
                        name="test1",
                        status=TestStatus.FAILED,
                        file="file1.py",
                        team="team-a",
                    ),
                    TestResult(
                        name="test2",
                        status=TestStatus.PASSED,
                        file="file2.py",
                        team="team-b",
                    ),
                ],
            ),
        ]

        summarizer = SummaryGenerator()
        report = summarizer.generate_report(runs)

        self.assertEqual(len(report.team_summaries), 2)
        self.assertEqual(len(report.file_summaries), 2)

        team_a = next(t for t in report.team_summaries if t.team == "team-a")
        self.assertEqual(team_a.total_tests, 1)
        self.assertEqual(team_a.flaky_tests, 1)

    def test_overall_flaky_rate(self):
        runs = []
        for i in range(3):
            runs.append(
                TestRun(
                    run_id=f"run_{i:03d}",
                    timestamp=f"2026-06-{10+i:02d}T10:00:00",
                    results=[
                        TestResult(
                            name="stable_test",
                            status=TestStatus.PASSED,
                            file="stable.py",
                            team="team-a",
                        ),
                        TestResult(
                            name="flaky_test",
                            status=TestStatus.PASSED if i % 2 == 0 else TestStatus.FAILED,
                            file="flaky.py",
                            team="team-a",
                        ),
                    ],
                )
            )

        summarizer = SummaryGenerator()
        report = summarizer.generate_report(runs)

        self.assertEqual(report.total_test_cases, 2)
        self.assertGreater(report.overall_flaky_rate, 0)

    def test_time_window_in_summarizer(self):
        old_date = (datetime.now() - timedelta(days=60)).isoformat()
        new_date = (datetime.now() - timedelta(days=5)).isoformat()

        runs = [
            TestRun(
                run_id="old",
                timestamp=old_date,
                results=[TestResult(
                    name="test",
                    status=TestStatus.FAILED,
                    file="test.py",
                    team="team",
                )],
            ),
            TestRun(
                run_id="new1",
                timestamp=new_date,
                results=[TestResult(
                    name="test",
                    status=TestStatus.PASSED,
                    file="test.py",
                    team="team",
                )],
            ),
            TestRun(
                run_id="new2",
                timestamp=new_date,
                results=[TestResult(
                    name="test",
                    status=TestStatus.PASSED,
                    file="test.py",
                    team="team",
                )],
            ),
        ]

        classifier = TestCaseClassifier(time_window_days=30)
        summarizer = SummaryGenerator(classifier=classifier)
        report = summarizer.generate_report(runs)

        self.assertEqual(report.total_runs, 2)


class TestOutputFormatter(unittest.TestCase):
    """Output formatter tests."""

    def setUp(self):
        runs = []
        for i in range(5):
            status = TestStatus.PASSED if i % 2 == 0 else TestStatus.FAILED
            runs.append(
                TestRun(
                    run_id=f"run_{i:03d}",
                    timestamp=f"2026-06-{10+i:02d}T10:00:00",
                    results=[
                        TestResult(
                            name="test_output",
                            status=status,
                            file="output_test.py",
                            team="test-team",
                        ),
                    ],
                )
            )

        summarizer = SummaryGenerator()
        self.report = summarizer.generate_report(runs)

    def test_json_output_has_version(self):
        json_str = OutputFormatter.format_json(self.report)
        data = json.loads(json_str)

        self.assertIn("schema_version", data)
        self.assertIn("tool_version", data)
        self.assertEqual(data["schema_version"], "1.1.0")
        self.assertEqual(data["tool_version"], "1.0.0")

    def test_json_output_has_fail_ratio_pct(self):
        json_str = OutputFormatter.format_json(self.report)
        data = json.loads(json_str)

        test_data = data["classified_tests"][0]
        self.assertIn("fail_ratio_pct", test_data)
        self.assertNotIn("recent_consecutive_failures", test_data)

    def test_json_output_structure(self):
        json_str = OutputFormatter.format_json(self.report)
        data = json.loads(json_str)

        self.assertIn("total_runs", data)
        self.assertIn("classified_tests", data)
        self.assertIn("team_summaries", data)
        self.assertIn("file_summaries", data)
        self.assertEqual(data["total_runs"], 5)

    def test_text_output(self):
        text = OutputFormatter.format_text_table(self.report)

        self.assertIn("TEST FLAKE SUMMARY REPORT", text)
        self.assertIn("BY TEAM SUMMARY", text)
        self.assertIn("BY FILE SUMMARY", text)
        self.assertIn("TEST CASE DETAILS", text)
        self.assertIn("Pass%", text)
        self.assertIn("Fail%", text)

    def test_text_output_show_only_flaky(self):
        text = OutputFormatter.format_text_table(self.report, show_only_flaky=True)

        self.assertIn("FLAKY", text)
        self.assertNotIn("STABLE_PASS", text)

    def test_text_output_show_all(self):
        text = OutputFormatter.format_text_table(self.report, show_all=True)

        self.assertIn("TEST CASE DETAILS", text)


class TestCLI(unittest.TestCase):
    """CLI tests."""

    def test_build_arg_parser(self):
        from flake_summary.cli import build_arg_parser

        parser = build_arg_parser()
        self.assertIsNotNone(parser)

        args = parser.parse_args(["--dir", "test_dir"])
        self.assertEqual(args.dir, "test_dir")
        self.assertEqual(args.format, "text")
        self.assertEqual(args.fail_ratio, 0.7)

        args = parser.parse_args(["--files", "a.xml", "b.xml", "--format", "json"])
        self.assertEqual(args.files, ["a.xml", "b.xml"])
        self.assertEqual(args.format, "json")

    def test_cli_has_http_options(self):
        from flake_summary.cli import build_arg_parser

        parser = build_arg_parser()
        args = parser.parse_args([
            "--dir", "test",
            "--basic-auth-user", "user",
            "--basic-auth-pass", "pass",
            "--bearer-token", "token",
            "--proxy", "http://proxy:8080",
        ])
        self.assertEqual(args.basic_auth_user, "user")
        self.assertEqual(args.basic_auth_pass, "pass")
        self.assertEqual(args.bearer_token, "token")
        self.assertEqual(args.proxy, "http://proxy:8080")

    def test_cli_has_classification_options(self):
        from flake_summary.cli import build_arg_parser

        parser = build_arg_parser()
        args = parser.parse_args([
            "--dir", "test",
            "--min-runs", "5",
            "--stable-threshold", "0.9",
            "--fail-ratio", "0.6",
            "--weights", "weights.json",
            "--time-window", "7",
        ])
        self.assertEqual(args.min_runs, 5)
        self.assertEqual(args.stable_threshold, 0.9)
        self.assertEqual(args.fail_ratio, 0.6)
        self.assertEqual(args.weights, "weights.json")
        self.assertEqual(args.time_window, 7)

    def test_main_with_sample_data(self):
        from flake_summary.cli import main

        sample_dir = os.path.join(
            os.path.dirname(__file__),
            "sample_data",
        )

        exit_code = main(["--dir", sample_dir])
        self.assertEqual(exit_code, 0)

    def test_main_with_json_output(self):
        from flake_summary.cli import main
        import tempfile

        sample_dir = os.path.join(
            os.path.dirname(__file__),
            "sample_data",
        )

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            temp_file = f.name

        try:
            exit_code = main([
                "--dir", sample_dir,
                "--format", "json",
                "--output", temp_file,
            ])
            self.assertEqual(exit_code, 0)

            with open(temp_file) as f:
                data = json.load(f)
            self.assertIn("schema_version", data)
            self.assertIn("total_runs", data)
            self.assertEqual(data["total_runs"], 5)
        finally:
            os.unlink(temp_file)

    def test_main_with_weights(self):
        from flake_summary.cli import main

        sample_dir = os.path.join(
            os.path.dirname(__file__),
            "sample_data",
        )
        weights_file = os.path.join(sample_dir, "weights_config.json")

        exit_code = main([
            "--dir", sample_dir,
            "--weights", weights_file,
        ])
        self.assertEqual(exit_code, 0)

    def test_main_with_time_window(self):
        from flake_summary.cli import main

        sample_dir = os.path.join(
            os.path.dirname(__file__),
            "sample_data",
        )

        exit_code = main([
            "--dir", sample_dir,
            "--time-window", "30",
        ])
        self.assertEqual(exit_code, 0)

    def test_main_with_fail_ratio(self):
        from flake_summary.cli import main

        sample_dir = os.path.join(
            os.path.dirname(__file__),
            "sample_data",
        )

        exit_code = main([
            "--dir", sample_dir,
            "--fail-ratio", "0.5",
        ])
        self.assertEqual(exit_code, 0)


if __name__ == "__main__":
    unittest.main()
