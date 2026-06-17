"""Command-line interface for test flake summary tool."""

import argparse
import os
import sys
from typing import List, Optional

from . import __version__
from .classifier import TestCaseClassifier, WeightsConfig
from .output import OutputFormatter
from .parser import HTTPConfig, TestResultParser
from .summarizer import SummaryGenerator


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Summarize flaky test results from CI runs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --dir test_results/
  %(prog)s --files run1.xml run2.xml run3.json
  %(prog)s --dir test_results/ --format json --output report.json
  %(prog)s --dir test_results/ --min-runs 5 --fail-ratio 0.7
  %(prog)s --dir test_results/ --only-flaky
  %(prog)s --files https://ci.example.com/results/run.xml --bearer-token your_token
  %(prog)s --dir test_results/ --weights weights.json
  %(prog)s --dir test_results/ --time-window 7
  %(prog)s --dir test_results/ --basic-auth-user user --basic-auth-pass pass
  %(prog)s --dir test_results/ --proxy http://proxy.example.com:8080
        """,
    )

    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        "--dir",
        type=str,
        help="Directory containing test result files (.xml or .json)",
    )
    input_group.add_argument(
        "--files",
        nargs="+",
        type=str,
        help="List of test result file paths or URLs",
    )

    http_group = parser.add_argument_group("HTTP Authentication Options")
    http_group.add_argument(
        "--basic-auth-user",
        type=str,
        help="Username for HTTP Basic Authentication",
    )
    http_group.add_argument(
        "--basic-auth-pass",
        type=str,
        help="Password for HTTP Basic Authentication",
    )
    http_group.add_argument(
        "--bearer-token",
        type=str,
        help="Bearer token for API authentication",
    )
    http_group.add_argument(
        "--proxy",
        type=str,
        help="Proxy server URL (e.g., http://proxy.example.com:8080)",
    )

    output_group = parser.add_argument_group("Output Options")
    output_group.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )
    output_group.add_argument(
        "--output",
        type=str,
        help="Output file path (default: stdout)",
    )

    classifier_group = parser.add_argument_group("Classification Options")
    classifier_group.add_argument(
        "--min-runs",
        type=int,
        default=3,
        help="Minimum number of runs to consider for classification (default: 3)",
    )
    classifier_group.add_argument(
        "--stable-threshold",
        type=float,
        default=0.95,
        help="Pass rate threshold for stable pass (default: 0.95)",
    )
    classifier_group.add_argument(
        "--fail-ratio",
        type=float,
        default=0.7,
        help="Failure ratio threshold for continuous fail (default: 0.7)",
    )
    classifier_group.add_argument(
        "--weights",
        type=str,
        help="Path to weights configuration file (JSON format)",
    )
    classifier_group.add_argument(
        "--time-window",
        type=int,
        help="Time window in days for filtering historical test runs",
    )

    display_group = parser.add_mutually_exclusive_group()
    display_group.add_argument(
        "--all",
        action="store_true",
        help="Show all test cases including stable passes",
    )
    display_group.add_argument(
        "--only-flaky",
        action="store_true",
        help="Show only flaky test cases",
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    return parser


def _build_http_config(args) -> HTTPConfig:
    http_config = HTTPConfig()

    if args.basic_auth_user and args.basic_auth_pass:
        http_config.basic_auth = {
            "username": args.basic_auth_user,
            "password": args.basic_auth_pass,
        }
    elif args.basic_auth_user or args.basic_auth_pass:
        raise ValueError(
            "Both --basic-auth-user and --basic-auth-pass must be provided together"
        )

    if args.bearer_token:
        http_config.bearer_token = args.bearer_token

    if args.proxy:
        http_config.proxy = {"http": args.proxy, "https": args.proxy}

    return http_config


def _build_weights_config(weights_file: Optional[str]) -> Optional[WeightsConfig]:
    if not weights_file:
        return None

    if not os.path.exists(weights_file):
        raise FileNotFoundError(f"Weights file not found: {weights_file}")

    weights = WeightsConfig.from_file(weights_file)
    weights.validate()
    return weights


def main(argv: List[str] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    try:
        http_config = _build_http_config(args)
        weights_config = _build_weights_config(args.weights)

        if args.dir:
            test_runs = TestResultParser.parse_directory(args.dir, http_config)
        else:
            test_runs = TestResultParser.parse_files(args.files, http_config)

        if not test_runs:
            print("Error: No valid test result files found.", file=sys.stderr)
            return 1

        classifier = TestCaseClassifier(
            min_runs=args.min_runs,
            stable_pass_threshold=args.stable_threshold,
            fail_ratio_threshold=args.fail_ratio,
            weights=weights_config,
            time_window_days=args.time_window,
        )

        summarizer = SummaryGenerator(classifier=classifier)
        report = summarizer.generate_report(test_runs)

        if args.format == "json":
            output = OutputFormatter.format_json(report)
        else:
            output = OutputFormatter.format_text_table(
                report,
                show_all=args.all,
                show_only_flaky=args.only_flaky,
            )

        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(output)
            print(f"Report written to {args.output}")
        else:
            print(output)

        return 0

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
