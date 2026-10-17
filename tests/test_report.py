from datetime import datetime, timezone
import json

from reprobot.models import (
    CommandResult,
    DetectionSummary,
    ExecutionReport,
    ReportStatus,
    RepositoryInfo,
)


def make_report() -> ExecutionReport:
    return ExecutionReport(
        status=ReportStatus.SUCCESS,
        repository=RepositoryInfo(
            path="/tmp/example",
            name="example",
            git_repository=True,
        ),
        detected=DetectionSummary(
            python=True,
            dependency_files=["requirements.txt"],
            lockfiles=[],
            test_configuration=["pytest.ini"],
        ),
        commands=[
            CommandResult(
                name="run tests",
                command=["python", "-m", "pytest"],
                exit_code=0,
                duration_seconds=1.25,
                stdout="1 passed",
                started_at=datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc),
            )
        ],
        summary="Tests passed.",
    )


def test_report_serializes_all_execution_evidence() -> None:
    report = make_report()

    payload = report.to_dict()

    assert payload["schema_version"] == 1
    assert payload["status"] == "success"
    assert payload["repository"]["git_repository"] is True
    assert payload["detected"]["dependency_files"] == ["requirements.txt"]
    assert payload["commands"][0]["command"] == ["python", "-m", "pytest"]
    assert payload["commands"][0]["exit_code"] == 0
    assert payload["commands"][0]["duration_seconds"] == 1.25
    assert payload["commands"][0]["started_at"] == "2026-10-17T12:00:00+00:00"


def test_report_json_is_valid_stable_and_newline_terminated() -> None:
    serialized = make_report().to_json()

    assert serialized.endswith("\n")
    assert json.loads(serialized) == json.loads(make_report().to_json())
    assert '"status": "success"' in serialized


def test_report_serializes_failed_and_timeout_evidence() -> None:
    report = ExecutionReport(
        status=ReportStatus.FAILED,
        repository=RepositoryInfo("/tmp/example", "example", True),
        commands=[
            CommandResult(
                name="install dependencies",
                command=["python", "-m", "pip", "install", "-r", "requirements.txt"],
                exit_code=None,
                duration_seconds=120.0,
                timed_out=True,
                error="Command exceeded timeout",
            )
        ],
        errors=["Dependency installation timed out."],
        summary="Dependency installation failed.",
    )

    command = json.loads(report.to_json())["commands"][0]

    assert json.loads(report.to_json())["status"] == "failed"
    assert command["exit_code"] is None
    assert command["timed_out"] is True
    assert command["error"] == "Command exceeded timeout"
