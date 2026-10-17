from pathlib import Path
from unittest.mock import Mock, patch

from reprobot.docker_runner import DockerRunner


def test_build_command_contains_security_and_resource_controls(tmp_path: Path) -> None:
    runner = DockerRunner()

    command = runner.build_command(tmp_path, ["python", "-c", "print('safe')"], container_name="test")

    assert command[:4] == ["docker", "run", "--rm", "--name"]
    assert "--network" in command
    assert command[command.index("--network") + 1] == "none"
    assert "--cap-drop" in command
    assert command[command.index("--cap-drop") + 1] == "ALL"
    assert "--security-opt" in command
    assert "no-new-privileges:true" in command
    assert "--read-only" in command
    assert "--cpus" in command
    assert "--memory" in command
    assert "--pids-limit" in command
    assert "--mount" in command
    mount = command[command.index("--mount") + 1]
    assert "destination=/workspace" in mount
    assert "readonly" in mount
    assert "--privileged" not in command
    assert "/var/run/docker.sock" not in " ".join(command)
    assert command[-3:] == ["python", "-c", "print('safe')"]


def test_build_command_rejects_missing_repository(tmp_path: Path) -> None:
    runner = DockerRunner()

    try:
        runner.build_command(tmp_path / "missing", ["true"])
    except ValueError as error:
        assert "does not exist" in str(error)
    else:
        raise AssertionError("missing repositories must be rejected")


@patch("reprobot.docker_runner.subprocess.run")
def test_check_available_reports_missing_docker(mock_run: Mock) -> None:
    from reprobot.docker_runner import DockerRunner

    mock_run.side_effect = FileNotFoundError

    result = DockerRunner.check_available()

    assert result.available is False
    assert result.error == "Docker CLI was not found on PATH."


@patch("reprobot.docker_runner.subprocess.run")
def test_check_available_reports_engine_failure(mock_run: Mock) -> None:
    mock_run.return_value = Mock(returncode=1, stdout="", stderr="daemon unavailable")

    result = DockerRunner.check_available()

    assert result.available is False
    assert "daemon unavailable" in result.error


@patch("reprobot.docker_runner.subprocess.Popen")
@patch("reprobot.docker_runner.subprocess.run")
def test_run_returns_command_evidence_and_cleans_up(mock_run: Mock, mock_popen: Mock, tmp_path: Path) -> None:
    availability = Mock(returncode=0, stdout="27.0.0", stderr="")
    mock_run.side_effect = [availability, Mock(returncode=0, stdout="", stderr="")]
    process = Mock(returncode=0)
    process.communicate.return_value = ("hello\n", "")
    mock_popen.return_value = process

    result = DockerRunner().run(tmp_path, ["python", "-c", "print('hello')"], name="smoke")

    assert result.name == "smoke"
    assert result.command == ["python", "-c", "print('hello')"]
    assert result.exit_code == 0
    assert result.stdout == "hello\n"
    assert result.stderr == ""
    assert result.timed_out is False
    assert result.error is None
    assert mock_run.call_args_list[1].args[0][:4] == ["docker", "rm", "--force", mock_run.call_args_list[1].args[0][3]]
    mock_popen.assert_called_once()
    assert mock_popen.call_args.kwargs["shell"] is False


@patch("reprobot.docker_runner.subprocess.Popen")
@patch("reprobot.docker_runner.subprocess.run")
def test_run_returns_timeout_evidence_and_attempts_cleanup(
    mock_run: Mock, mock_popen: Mock, tmp_path: Path
) -> None:
    mock_run.side_effect = [Mock(returncode=0, stdout="3.12", stderr=""), Mock(returncode=0)]
    process = Mock(returncode=-9)
    process.communicate.side_effect = [
        __import__("subprocess").TimeoutExpired(["docker", "run"], 0.01, output="partial"),
        ("partial", "")
    ]
    mock_popen.return_value = process

    result = DockerRunner(timeout_seconds=0.01).run(tmp_path, ["python", "-c", "sleep"])

    assert result.exit_code is None
    assert result.timed_out is True
    assert result.stdout == "partial"
    assert "exceeded" in result.error
    process.kill.assert_called_once()
    assert mock_run.call_count == 2
