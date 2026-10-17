"""Safe, non-executing inspection of local Python repositories."""

from __future__ import annotations

from pathlib import Path
import subprocess

from .models import (
    DetectionResult,
    LockfileDetection,
    RepositoryInfo,
)


_DEPENDENCY_NAMES = {"pyproject.toml", "setup.py", "setup.cfg"}
_SUPPORTED_LOCKFILES = {
    "requirements.lock": "pip requirements lockfile",
}
_RECOGNIZED_UNSUPPORTED_LOCKFILES = {
    "poetry.lock": "Poetry lockfile",
    "uv.lock": "uv lockfile",
    "Pipfile.lock": "Pipenv lockfile",
    "pdm.lock": "PDM lockfile",
}
_SKIPPED_DIRECTORIES = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    "node_modules",
}


def detect_repository(path: str | Path) -> DetectionResult:
    """Inspect ``path`` and return structured findings without running its code."""

    requested_path = Path(path).expanduser()
    if not requested_path.exists():
        repository = RepositoryInfo(str(requested_path.absolute()), requested_path.name, False)
        return DetectionResult(
            supported=False,
            repository=repository,
            python_project=False,
            reasons=["The supplied path does not exist."],
        )

    if not requested_path.is_dir():
        repository = RepositoryInfo(str(requested_path.absolute()), requested_path.name, False)
        return DetectionResult(
            supported=False,
            repository=repository,
            python_project=False,
            reasons=["The supplied path is not a directory."],
        )

    path = requested_path.resolve()
    git_repository, git_reason = _check_git_repository(path)
    files = _project_files(path)
    dependency_files = _dependency_files(path, files)
    lockfiles = _lockfile_detections(path, files)
    python_project = bool(dependency_files or any(file.suffix == ".py" for file in files))
    test_configuration = _test_configuration(path, files)
    test_frameworks, tests_exist = _test_frameworks(files, test_configuration)

    reasons: list[str] = []
    if not git_repository:
        reasons.append(git_reason)
    if not python_project:
        reasons.append("No supported Python project markers were found.")
    for lockfile in lockfiles:
        if not lockfile.supported:
            reasons.append(lockfile.reason)
    if not tests_exist:
        reasons.append("No likely test files were found.")

    repository = RepositoryInfo(str(path), path.name, git_repository)
    supported = git_repository and python_project and all(
        lockfile.supported for lockfile in lockfiles
    )
    return DetectionResult(
        supported=supported,
        repository=repository,
        python_project=python_project,
        dependency_files=dependency_files,
        lockfiles=lockfiles,
        test_configuration=test_configuration,
        test_frameworks=test_frameworks,
        tests_exist=tests_exist,
        reasons=reasons,
    )


def _check_git_repository(path: Path) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False, "Git could not verify the supplied directory."
    if result.returncode == 0 and result.stdout.strip() == "true":
        return True, ""
    return False, "The supplied directory is not a valid local Git repository."


def _project_files(path: Path) -> list[Path]:
    files: list[Path] = []
    for candidate in path.rglob("*"):
        if candidate.is_file() and not _has_skipped_directory(candidate, path):
            files.append(candidate)
    return sorted(files)


def _has_skipped_directory(candidate: Path, root: Path) -> bool:
    return any(part in _SKIPPED_DIRECTORIES for part in candidate.relative_to(root).parts[:-1])


def _relative(file: Path, root: Path) -> str:
    return file.relative_to(root).as_posix()


def _dependency_files(root: Path, files: list[Path]) -> list[str]:
    result: list[str] = []
    for file in files:
        if file.name in _DEPENDENCY_NAMES or (
            file.name.startswith("requirements") and file.suffix == ".txt"
        ):
            result.append(_relative(file, root))
    return sorted(result)


def _lockfile_detections(root: Path, files: list[Path]) -> list[LockfileDetection]:
    result: list[LockfileDetection] = []
    for file in files:
        if file.name in _SUPPORTED_LOCKFILES:
            result.append(
                LockfileDetection(
                    path=_relative(file, root),
                    format=_SUPPORTED_LOCKFILES[file.name],
                    supported=True,
                    reason="This lockfile format is recognized for the initial execution plan.",
                )
            )
        elif file.name in _RECOGNIZED_UNSUPPORTED_LOCKFILES:
            result.append(
                LockfileDetection(
                    path=_relative(file, root),
                    format=_RECOGNIZED_UNSUPPORTED_LOCKFILES[file.name],
                    supported=False,
                    reason=(
                        f"Lockfile '{file.name}' is recognized but is not supported for "
                        "execution in this version."
                    ),
                )
            )
    return sorted(result, key=lambda lockfile: lockfile.path)


def _test_configuration(root: Path, files: list[Path]) -> list[str]:
    result: list[str] = []
    for file in files:
        if file.name in {"pytest.ini", "tox.ini", "setup.cfg"}:
            result.append(_relative(file, root))
        elif file.name == "pyproject.toml":
            try:
                text = file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if "[tool.pytest" in text:
                result.append(_relative(file, root))
    return sorted(set(result))


def _test_frameworks(files: list[Path], configuration: list[str]) -> tuple[list[str], bool]:
    tests = [
        file
        for file in files
        if file.name.startswith("test_") or file.name.endswith("_test.py")
    ]
    frameworks: set[str] = set()
    if any(
        path == "pytest.ini"
        or path.endswith("/pytest.ini")
        or path == "pyproject.toml"
        or path.endswith("/pyproject.toml")
        for path in configuration
    ):
        frameworks.add("pytest")
    if any(path == "tox.ini" or path.endswith("/tox.ini") for path in configuration):
        frameworks.add("unknown")
    for file in tests:
        try:
            text = file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if "import unittest" in text or "from unittest" in text or "TestCase" in text:
            frameworks.add("unittest")
        if "import pytest" in text or "from pytest" in text:
            frameworks.add("pytest")
    if tests and not frameworks:
        frameworks.add("unknown")
    return sorted(frameworks), bool(tests)
