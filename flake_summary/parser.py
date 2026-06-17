"""Test result parser - supports JUnit XML format from CI systems."""

import json
import os
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import List, Optional
from urllib.parse import urlparse
from urllib.request import urlopen

from .models import TestResult, TestRun, TestStatus


class TestResultParser:
    """Parser for test result files from CI systems."""

    @staticmethod
    def parse_file(file_path: str) -> TestRun:
        parsed = urlparse(file_path)
        if parsed.scheme in ("http", "https"):
            return TestResultParser._parse_url(file_path)
        return TestResultParser._parse_local_file(file_path)

    @staticmethod
    def _parse_url(url: str) -> TestRun:
        with urlopen(url) as response:
            content = response.read()
            run_id = os.path.basename(urlparse(url).path) or url
            return TestResultParser._parse_content(content, run_id)

    @staticmethod
    def _parse_local_file(file_path: str) -> TestRun:
        with open(file_path, "rb") as f:
            content = f.read()
        run_id = os.path.basename(file_path)
        return TestResultParser._parse_content(content, run_id)

    @staticmethod
    def _parse_content(content: bytes, run_id: str) -> TestRun:
        try:
            return TestResultParser._parse_junit_xml(content, run_id)
        except ET.ParseError:
            try:
                return TestResultParser._parse_json(content, run_id)
            except json.JSONDecodeError:
                raise ValueError(
                    f"Unsupported format for run {run_id}. Expected JUnit XML or JSON."
                )

    @staticmethod
    def _parse_junit_xml(content: bytes, run_id: str) -> TestRun:
        root = ET.fromstring(content)

        timestamp = root.get("timestamp", "")
        if not timestamp:
            timestamp = datetime.now().isoformat()

        test_run = TestRun(run_id=run_id, timestamp=timestamp)

        for testcase in root.iter("testcase"):
            name = testcase.get("name", "")
            classname = testcase.get("classname", "")
            file_attr = testcase.get("file", classname)
            team = testcase.get("team", "unknown")
            duration = float(testcase.get("time", "0") or "0")

            status = TestStatus.PASSED
            message = None

            failure = testcase.find("failure")
            error = testcase.find("error")
            skipped = testcase.find("skipped")

            if failure is not None:
                status = TestStatus.FAILED
                message = failure.get("message", failure.text or "")
            elif error is not None:
                status = TestStatus.FAILED
                message = error.get("message", error.text or "")
            elif skipped is not None:
                status = TestStatus.SKIPPED
                message = skipped.get("message", skipped.text or "")

            test_name = f"{classname}.{name}" if classname else name

            test_run.results.append(
                TestResult(
                    name=test_name,
                    status=status,
                    file=file_attr,
                    team=team,
                    duration=duration,
                    message=message,
                )
            )

        return test_run

    @staticmethod
    def _parse_json(content: bytes, run_id: str) -> TestRun:
        data = json.loads(content)

        timestamp = data.get("timestamp", datetime.now().isoformat())
        test_run = TestRun(run_id=run_id, timestamp=timestamp)

        for result_data in data.get("results", []):
            status_str = result_data.get("status", "passed").lower()
            if status_str == "passed":
                status = TestStatus.PASSED
            elif status_str in ("failed", "failure", "error"):
                status = TestStatus.FAILED
            elif status_str == "skipped":
                status = TestStatus.SKIPPED
            else:
                status = TestStatus.PASSED

            test_run.results.append(
                TestResult(
                    name=result_data.get("name", ""),
                    status=status,
                    file=result_data.get("file", ""),
                    team=result_data.get("team", "unknown"),
                    duration=float(result_data.get("duration", 0)),
                    message=result_data.get("message"),
                )
            )

        return test_run

    @staticmethod
    def parse_directory(directory: str) -> List[TestRun]:
        runs = []
        for filename in sorted(os.listdir(directory)):
            filepath = os.path.join(directory, filename)
            if os.path.isfile(filepath) and (
                filename.endswith(".xml") or filename.endswith(".json")
            ):
                try:
                    runs.append(TestResultParser.parse_file(filepath))
                except (ValueError, ET.ParseError, json.JSONDecodeError):
                    continue
        return runs

    @staticmethod
    def parse_files(file_paths: List[str]) -> List[TestRun]:
        runs = []
        for path in file_paths:
            try:
                runs.append(TestResultParser.parse_file(path))
            except Exception as e:
                print(f"Warning: Failed to parse {path}: {e}")
        return runs
