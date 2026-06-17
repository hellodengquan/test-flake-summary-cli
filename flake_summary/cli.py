"""Command-line interface for test flake summary tool."""

import argparse
import sys
from typing import List

from . import __version__
from .classifier import TestCaseClassifier
from .output import OutputFormatter
from .parser import TestResultParser
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
  %(prog)s --dir test_results/ --min-runs 5 --consecutive-fail 3
  %(prog)s --dir test_results/ --only-flaky
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

    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Output file path (default: stdout)",
    )

    parser.add_argument(
        "--min-runs",
        type=int,
        default=3,
        help="Minimum number of runs to consider for classification (default: 3)",
    )
    parser.add_argument(
        "--stable-threshold",
        type=float,
        default=0.95,
        help="Pass rate threshold for stable pass (default: 0.95)",
    )
    parser.add_argument(
        "--consecutive-fail",
        type=int,
        default=3,
        help="Consecutive failures threshold (default: 3)",
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


def main(argv: List[str] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    try:
        if args.dir:
            test_runs = TestResultParser.parse_directory(args.dir)
        else:
            test_runs = TestResultParser.parse_files(args.files)

        if not test_runs:
            print("Error: No valid test result files found.", file=sys.stderr)
            return 1

        classifier = TestCaseClassifier(
            min_runs=args.min_runs,
            stable_pass_threshold=args.stable_threshold,
            consecutive_fail_threshold=args.consecutive_fail,
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
