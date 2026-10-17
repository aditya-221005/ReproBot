"""Command-line workflow for detecting and testing a local repository."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Sequence

from .detector import detect_repository
from .docker_runner import DockerRunner
from .models import (
    CommandResult,
    DetectionResult,
    DetectionSummary,
    ExecutionReport,
    ReportStatus,
)


EXIT_SUCCESS = 0
EXIT_FAILED = 1
EXIT_UNSUPPORTED = 2


def build_parser() -> argparse.ArgumentParser:
    """Create the ReproBot command-line parser."""

    parser = argparse.ArgumentParser(
        prog="reprobot",
        description=(
            "Inspect a local Python Git repository and run its detected tests "
            "inside a restricted Docker container."
        ),
    )
    parser.add_argument(
        "repository",
        type=Path,
        help="path to the local Git repository to inspect",
    )
    parser.add_argument(
        "--report",
        type=Path,
        help="write the structured JSON report to this path",
    )
    return parser


def select_test_command(detection: DetectionResult) -> tuple[list[str] | None, str | None]:
    """Select a test command only when detector evidence is sufficient."""

    if not detection.tests_exist:
        return None, "No likely test files were found; no test command was selected."
    if "pytest" in detection.test_frameworks:
        return ["python", "-m", "pytest"], None
    if "unittest" in detection.test_frameworks:
        return ["python", "-m", "unittest", "discover"], None
    return None, "Tests appear to exist, but no supported test framework was identified."


def _detection_summary(detection: DetectionResult) -> DetectionSummary:
    """Adapt detector output to the report model used by the workflow."""

    lockfiles = [lockfile.path for lockfile in detection.lockfiles]
    supported = [lockfile.path for lockfile in detection.lockfiles if lockfile.supported]
    unsupported = [lockfile.path for lockfile in detection.lockfiles if not lockfile.supported]
    return DetectionSummary(
        python=detection.python_project,
        dependency_files=list(detection.dependency_files),
        lockfiles=lockfiles,
        test_configuration=list(detection.test_configuration),
        lockfiles_supported=supported,
        lockfiles_unsupported=unsupported,
        test_frameworks=list(detection.test_frameworks),
        tests_exist=detection.tests_exist,
    )


def _unsupported_report(
    detection: DetectionResult,
    *,
    extra_reason: str | None = None,
) -> ExecutionReport:
    errors = list(detection.reasons)
    if extra_reason and extra_reason not in errors:
        errors.append(extra_reason)
    return ExecutionReport(
        status=ReportStatus.UNSUPPORTED,
        repository=detection.repository,
        detected=_detection_summary(detection),
        errors=errors,
        summary="Repository is not supported for the current ReproBot workflow.",
    )


def run_workflow(
    repository: str | Path,
    *,
    runner: DockerRunner | None = None,
) -> tuple[int, ExecutionReport]:
    """Run detection and one selected test command, returning exit code/report."""

    detection = detect_repository(repository)
    if not detection.supported:
        return EXIT_UNSUPPORTED, _unsupported_report(detection)

    test_command, selection_error = select_test_command(detection)
    if test_command is None:
        return EXIT_UNSUPPORTED, _unsupported_report(detection, extra_reason=selection_error)

    command_runner = runner or DockerRunner()
    command_result = command_runner.run(
        detection.repository.path,
        test_command,
        name="run tests",
    )
    if command_result.exit_code == 0 and not command_result.timed_out and not command_result.error:
        return EXIT_SUCCESS, ExecutionReport(
            status=ReportStatus.SUCCESS,
            repository=detection.repository,
            detected=_detection_summary(detection),
            commands=[command_result],
            summary="Detected tests passed inside the restricted Docker container.",
        )

    errors = list(detection.reasons)
    if command_result.error:
        errors.append(command_result.error)
    elif command_result.stderr.strip():
        errors.append(command_result.stderr.strip())
    return EXIT_FAILED, ExecutionReport(
        status=ReportStatus.FAILED,
        repository=detection.repository,
        detected=_detection_summary(detection),
        commands=[command_result],
        errors=errors,
        summary="Detected tests did not complete successfully.",
    )


def _write_or_print_report(report: ExecutionReport, output_path: Path | None) -> bool:
    if output_path is None:
        print(report.to_json(), end="")
        return True
    try:
        report.write_json(output_path)
    except OSError as error:
        print(f"reprobot: could not write report: {error}", file=sys.stderr)
        return False
    print(f"reprobot: {report.status.value}")
    print(f"report: {output_path}")
    return True


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return a process exit code."""

    args = build_parser().parse_args(argv)
    exit_code, report = run_workflow(args.repository)
    if not _write_or_print_report(report, args.report):
        return EXIT_FAILED
    return exit_code
