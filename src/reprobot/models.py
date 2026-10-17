"""Data models for ReproBot execution reports."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import StrEnum
import json
from pathlib import Path
from typing import Any


class ReportStatus(StrEnum):
    """The top-level result of an attempted repository run."""

    SUCCESS = "success"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class RepositoryInfo:
    """Basic information about the repository being examined."""

    path: str
    name: str
    git_repository: bool


@dataclass(frozen=True)
class DetectionSummary:
    """Files and configuration discovered before execution."""

    python: bool = False
    dependency_files: list[str] = field(default_factory=list)
    lockfiles: list[str] = field(default_factory=list)
    test_configuration: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CommandResult:
    """Evidence captured for one command executed by ReproBot."""

    name: str
    command: list[str]
    exit_code: int | None
    duration_seconds: float
    stdout: str = ""
    stderr: str = ""
    started_at: datetime | None = None
    timed_out: bool = False
    error: str | None = None


@dataclass(frozen=True)
class ExecutionReport:
    """Structured result of examining and, eventually, running a repository."""

    status: ReportStatus
    repository: RepositoryInfo
    detected: DetectionSummary = field(default_factory=DetectionSummary)
    commands: list[CommandResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    summary: str = ""
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation of this report."""

        value = asdict(self)
        value["status"] = self.status.value
        for command, command_value in zip(self.commands, value["commands"]):
            if command.started_at is not None:
                command_value["started_at"] = command.started_at.isoformat()
        return value

    def to_json(self, *, indent: int = 2) -> str:
        """Serialize this report as stable, human-readable JSON."""

        return json.dumps(self.to_dict(), indent=indent, sort_keys=True) + "\n"

    def write_json(self, path: str | Path, *, indent: int = 2) -> None:
        """Write this report to a UTF-8 JSON file."""

        Path(path).write_text(self.to_json(indent=indent), encoding="utf-8")
