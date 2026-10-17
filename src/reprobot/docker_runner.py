"""Restricted Docker command execution for ReproBot.

This module deliberately runs one explicitly supplied command at a time. It
does not install dependencies, choose test commands, or inspect repositories.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import subprocess
import time
from pathlib import Path
from uuid import uuid4

from .models import CommandResult


DEFAULT_IMAGE = "python:3.12.8-slim-bookworm"
DEFAULT_TIMEOUT_SECONDS = 120.0
DEFAULT_CPUS = "1"
DEFAULT_MEMORY = "512m"
DEFAULT_PIDS_LIMIT = "128"
CONTAINER_WORKDIR = "/workspace"


@dataclass(frozen=True)
class DockerAvailability:
    """Result of checking whether the Docker engine can accept commands."""

    available: bool
    version: str | None = None
    error: str | None = None


class DockerRunner:
    """Run explicitly supplied commands in short-lived restricted containers."""

    def __init__(
        self,
        *,
        image: str = DEFAULT_IMAGE,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        cpus: str = DEFAULT_CPUS,
        memory: str = DEFAULT_MEMORY,
        pids_limit: str = DEFAULT_PIDS_LIMIT,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        self.image = image
        self.timeout_seconds = timeout_seconds
        self.cpus = cpus
        self.memory = memory
        self.pids_limit = pids_limit

    @staticmethod
    def check_available(*, timeout_seconds: float = 10.0) -> DockerAvailability:
        """Check both Docker CLI availability and whether its engine is running."""

        try:
            result = subprocess.run(
                ["docker", "info", "--format", "{{.ServerVersion}}"],
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
                shell=False,
            )
        except FileNotFoundError:
            return DockerAvailability(
                available=False,
                error="Docker CLI was not found on PATH.",
            )
        except subprocess.TimeoutExpired:
            return DockerAvailability(
                available=False,
                error="Docker engine availability check timed out.",
            )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            message = "Docker engine is unavailable."
            if detail:
                message = f"{message} {detail}"
            return DockerAvailability(available=False, error=message)
        return DockerAvailability(available=True, version=result.stdout.strip() or None)

    def build_command(
        self,
        repository: str | Path,
        command: list[str],
        *,
        container_name: str = "reprobot-runner",
    ) -> list[str]:
        """Build the Docker CLI argument list without invoking a shell."""

        repository_path = self._validate_repository(repository)
        if not command or any(not isinstance(argument, str) for argument in command):
            raise ValueError("command must contain at least one string argument")

        return [
            "docker",
            "run",
            "--rm",
            "--name",
            container_name,
            "--workdir",
            CONTAINER_WORKDIR,
            "--mount",
            f"type=bind,source={repository_path},destination={CONTAINER_WORKDIR},readonly",
            "--network",
            "none",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,nodev,size=64m",
            "--cpus",
            self.cpus,
            "--memory",
            self.memory,
            "--pids-limit",
            self.pids_limit,
            self.image,
            *command,
        ]

    def run(
        self,
        repository: str | Path,
        command: list[str],
        *,
        name: str = "docker command",
    ) -> CommandResult:
        """Run one command and return evidence, including infrastructure errors."""

        started_at = datetime.now(timezone.utc)
        started_monotonic = time.monotonic()
        container_name = f"reprobot-{uuid4().hex}"
        try:
            docker_command = self.build_command(
                repository,
                command,
                container_name=container_name,
            )
        except (OSError, ValueError) as error:
            return self._result(
                name=name,
                command=command,
                started_at=started_at,
                started_monotonic=started_monotonic,
                error=str(error),
            )

        availability = self.check_available()
        if not availability.available:
            return self._result(
                name=name,
                command=command,
                started_at=started_at,
                started_monotonic=started_monotonic,
                error=availability.error or "Docker is unavailable.",
            )

        process: subprocess.Popen[str] | None = None
        try:
            process = subprocess.Popen(
                docker_command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                shell=False,
            )
            stdout, stderr = process.communicate(timeout=self.timeout_seconds)
            return self._result(
                name=name,
                command=command,
                started_at=started_at,
                started_monotonic=started_monotonic,
                exit_code=process.returncode,
                stdout=stdout,
                stderr=stderr,
                error=None if process.returncode == 0 else "Docker command failed.",
            )
        except subprocess.TimeoutExpired as error:
            if process is not None:
                process.kill()
                stdout, stderr = process.communicate()
            else:
                stdout, stderr = "", ""
            return self._result(
                name=name,
                command=command,
                started_at=started_at,
                started_monotonic=started_monotonic,
                exit_code=None,
                stdout=self._output(stdout, error.stdout),
                stderr=self._output(stderr, error.stderr),
                timed_out=True,
                error=f"Docker command exceeded {self.timeout_seconds:g} seconds.",
            )
        except OSError as error:
            return self._result(
                name=name,
                command=command,
                started_at=started_at,
                started_monotonic=started_monotonic,
                error=f"Docker command could not be started: {error}",
            )
        except KeyboardInterrupt:
            if process is not None:
                process.kill()
                process.communicate()
            raise
        finally:
            self._remove_container(container_name)

    @staticmethod
    def _validate_repository(repository: str | Path) -> Path:
        path = Path(repository).expanduser().resolve()
        if not path.exists():
            raise ValueError("The selected repository does not exist.")
        if not path.is_dir():
            raise ValueError("The selected repository is not a directory.")
        return path

    @staticmethod
    def _output(primary: str | bytes | None, secondary: str | bytes | None) -> str:
        value = primary if primary not in (None, "") else secondary
        if value is None:
            return ""
        return value.decode(errors="replace") if isinstance(value, bytes) else value

    def _remove_container(self, container_name: str) -> None:
        """Best-effort cleanup; never replace the original execution evidence."""

        try:
            subprocess.run(
                ["docker", "rm", "--force", container_name],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
                shell=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            pass

    @staticmethod
    def _result(
        *,
        name: str,
        command: list[str],
        started_at: datetime,
        started_monotonic: float,
        exit_code: int | None = None,
        stdout: str = "",
        stderr: str = "",
        timed_out: bool = False,
        error: str | None = None,
    ) -> CommandResult:
        return CommandResult(
            name=name,
            command=list(command),
            exit_code=exit_code,
            duration_seconds=max(0.0, time.monotonic() - started_monotonic),
            stdout=stdout,
            stderr=stderr,
            started_at=started_at,
            timed_out=timed_out,
            error=error,
        )
