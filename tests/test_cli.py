from pathlib import Path
import subprocess
from unittest.mock import Mock, patch

from reprobot.cli import (
    EXIT_FAILED,
    EXIT_SUCCESS,
    EXIT_UNSUPPORTED,
    main,
    run_workflow,
    select_test_command,
)
from reprobot.models import CommandResult


def initialize_git_repository(path: Path) -> None:
    subprocess.run(
        ["git", "init", "--quiet", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )


def make_unittest_repository(path: Path) -> None:
    path.mkdir()
    initialize_git_repository(path)
    (path / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    (path / "test_app.py").write_text(
        "import unittest\n\nclass AppTest(unittest.TestCase):\n"
        "    def test_value(self):\n        self.assertEqual(1, 1)\n",
        encoding="utf-8",
    )


def test_select_test_command_requires_test_evidence(tmp_path: Path) -> None:
    repository = tmp_path / "project"
    make_unittest_repository(repository)
    from reprobot.detector import detect_repository

    detection = detect_repository(repository)

    command, error = select_test_command(detection)

    assert command == ["python", "-m", "unittest", "discover"]
    assert error is None


def test_unsupported_repository_writes_report_without_running_docker(tmp_path: Path) -> None:
    repository = tmp_path / "unsupported"
    repository.mkdir()
    (repository / "README.md").write_text("not a Python repository\n", encoding="utf-8")
    report_path = tmp_path / "unsupported.json"

    with patch("reprobot.cli.DockerRunner.run") as docker_run:
        exit_code = main([str(repository), "--report", str(report_path)])

    assert exit_code == EXIT_UNSUPPORTED
    docker_run.assert_not_called()
    report = report_path.read_text(encoding="utf-8")
    assert '"status": "unsupported"' in report
    assert "not a valid local Git repository" in report


def test_successful_workflow_writes_report_and_uses_docker_runner(tmp_path: Path) -> None:
    repository = tmp_path / "passing"
    make_unittest_repository(repository)
    report_path = tmp_path / "passing.json"
    command_result = CommandResult(
        name="run tests",
        command=["python", "-m", "unittest", "discover"],
        exit_code=0,
        duration_seconds=0.2,
        stdout="OK\n",
    )
    runner = Mock()
    runner.run.return_value = command_result

    exit_code, report = run_workflow(repository, runner=runner)
    report.write_json(report_path)

    assert exit_code == EXIT_SUCCESS
    assert report.status.value == "success"
    assert report_path.exists()
    runner.run.assert_called_once_with(
        str(repository.resolve()),
        ["python", "-m", "unittest", "discover"],
        name="run tests",
    )


def test_failed_docker_execution_is_reported_honestly(tmp_path: Path) -> None:
    repository = tmp_path / "failing"
    make_unittest_repository(repository)
    runner = Mock()
    runner.run.return_value = CommandResult(
        name="run tests",
        command=["python", "-m", "unittest", "discover"],
        exit_code=1,
        duration_seconds=0.1,
        stderr="FAILED\n",
        error="Docker command failed.",
    )

    exit_code, report = run_workflow(repository, runner=runner)

    assert exit_code == EXIT_FAILED
    assert report.status.value == "failed"
    assert report.commands[0].exit_code == 1
    assert "Docker command failed." in report.errors


def test_cli_help_is_available(capsys) -> None:
    try:
        main(["--help"])
    except SystemExit as error:
        assert error.code == 0
    captured = capsys.readouterr()

    assert "path to the local Git repository" in captured.out
    assert "--report" in captured.out
