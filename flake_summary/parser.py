"""Test result parser - supports JUnit XML format from CI systems."""

import base64
import json
import os
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import (
    HTTPBasicAuthHandler,
    HTTPPasswordMgrWithDefaultRealm,
    ProxyHandler,
    Request,
    build_opener,
    install_opener,
    urlopen,
)

from .models import TestResult, TestRun, TestStatus


@dataclass
class HTTPConfig:
    """Configuration for HTTP requests."""

    basic_auth: Optional[Dict[str, str]] = None
    bearer_token: Optional[str] = None
    token_refresh_fn: Optional[Callable[[], str]] = None
    max_refresh_retries: int = 1
    proxy: Optional[Dict[str, str]] = None
    custom_headers: Dict[str, str] = field(default_factory=dict)
    request_timeout: int = 30
    on_auth_exhausted: str = "abort"

    VALID_ON_AUTH_EXHAUSTED = ("abort", "readonly")

    def __post_init__(self):
        if self.on_auth_exhausted not in self.VALID_ON_AUTH_EXHAUSTED:
            raise ValueError(
                f"on_auth_exhausted must be one of {self.VALID_ON_AUTH_EXHAUSTED}, "
                f"got '{self.on_auth_exhausted}'"
            )

    def has_auth(self) -> bool:
        return (
            self.basic_auth is not None
            or self.bearer_token is not None
            or self.proxy is not None
        )

    def can_refresh_token(self) -> bool:
        return self.bearer_token is not None and self.token_refresh_fn is not None


class TestResultParser:
    """Parser for test result files from CI systems."""

    @staticmethod
    def parse_file(file_path: str, http_config: Optional[HTTPConfig] = None) -> TestRun:
        parsed = urlparse(file_path)
        if parsed.scheme in ("http", "https"):
            return TestResultParser._parse_url(file_path, http_config)
        return TestResultParser._parse_local_file(file_path)

    @staticmethod
    def _parse_url(url: str, http_config: Optional[HTTPConfig] = None) -> TestRun:
        http_config = http_config or HTTPConfig()
        current_token = http_config.bearer_token
        original_token = http_config.bearer_token
        refresh_attempts = 0

        while True:
            try:
                content = TestResultParser._fetch_url(url, http_config, current_token)
                run_id = os.path.basename(urlparse(url).path) or url
                return TestResultParser._parse_content(content, run_id)
            except HTTPError as e:
                if e.code in (401, 403) and http_config.can_refresh_token() and refresh_attempts < http_config.max_refresh_retries:
                    try:
                        new_token = http_config.token_refresh_fn()
                        current_token = new_token
                        http_config.bearer_token = new_token
                        refresh_attempts += 1
                        continue
                    except Exception:
                        http_config.bearer_token = original_token
                        current_token = original_token
                        refresh_attempts = http_config.max_refresh_retries
                        continue

                if e.code in (401, 403) and http_config.on_auth_exhausted == "readonly":
                    try:
                        content = TestResultParser._fetch_url(url, http_config, token=None)
                        run_id = os.path.basename(urlparse(url).path) or url
                        return TestResultParser._parse_content(content, run_id)
                    except Exception:
                        raise e

                raise
            except URLError:
                raise

    @staticmethod
    def _fetch_url(
        url: str,
        http_config: HTTPConfig,
        token: Optional[str] = None,
    ) -> bytes:
        headers = {}
        handlers = []

        if http_config.basic_auth:
            username = http_config.basic_auth.get("username", "")
            password = http_config.basic_auth.get("password", "")
            credentials = base64.b64encode(
                f"{username}:{password}".encode()
            ).decode("ascii")
            headers["Authorization"] = f"Basic {credentials}"

        if token:
            headers["Authorization"] = f"Bearer {token}"

        if http_config.custom_headers:
            headers.update(http_config.custom_headers)

        if http_config.proxy:
            proxy_handler = ProxyHandler(http_config.proxy)
            handlers.append(proxy_handler)

        request = Request(url, headers=headers)

        if handlers:
            opener = build_opener(*handlers)
            install_opener(opener)

        with urlopen(request, timeout=http_config.request_timeout) as response:
            return response.read()

    @staticmethod
    def _parse_local_file(file_path: str) -> TestRun:
        with open(file_path, "rb") as f:
            content = f.read()
        run_id = os.path.basename(file_path)
        return TestResultParser._parse_content(content, run_id)

    @staticmethod
    def _parse_content(content: bytes, run_id: str) -> TestRun:
        test_run = None
        try:
            test_run = TestResultParser._parse_junit_xml(content, run_id)
        except ET.ParseError:
            try:
                test_run = TestResultParser._parse_json(content, run_id)
            except json.JSONDecodeError:
                raise ValueError(
                    f"Unsupported format for run {run_id}. Expected JUnit XML or JSON."
                )

        if test_run is None or len(test_run.results) == 0:
            raise ValueError(
                f"No test results found in run {run_id}. Not a valid test result file."
            )

        return test_run

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
    def parse_directory(
        directory: str,
        http_config: Optional[HTTPConfig] = None,
    ) -> List[TestRun]:
        runs = []
        for filename in sorted(os.listdir(directory)):
            filepath = os.path.join(directory, filename)
            if os.path.isfile(filepath) and (
                filename.endswith(".xml") or filename.endswith(".json")
            ):
                try:
                    runs.append(TestResultParser.parse_file(filepath, http_config))
                except (ValueError, ET.ParseError, json.JSONDecodeError):
                    continue
        return runs

    @staticmethod
    def parse_files(
        file_paths: List[str],
        http_config: Optional[HTTPConfig] = None,
    ) -> List[TestRun]:
        runs = []
        for path in file_paths:
            try:
                runs.append(TestResultParser.parse_file(path, http_config))
            except Exception as e:
                print(f"Warning: Failed to parse {path}: {e}")
        return runs
