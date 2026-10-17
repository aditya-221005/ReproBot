# ReproBot

ReproBot is a small open-source command-line tool for collecting honest,
repeatable evidence about a local Python Git repository. It inspects the
repository, selects a test command only when it has enough evidence to do so,
and runs that command in a restricted Docker container. The result is a
structured JSON report containing what ReproBot detected, what it attempted,
and what actually happened.

The first release is intentionally a focused build-and-test foundation rather
than an AI wrapper or an automatic repair system.

## Current status

The current milestone provides:

- Local Git repository validation.
- Python project marker detection.
- Dependency-file detection for `pyproject.toml`, `setup.py`, `setup.cfg`,
  and `requirements*.txt` files.
- Explicit lockfile recognition. `requirements.lock` is the only lockfile
  format currently marked as supported; Poetry, uv, Pipenv, and PDM lockfiles
  are recognized but reported as unsupported for execution.
- Likely test-file and test-framework detection for pytest and unittest.
- Test command selection for:
  - `python -m pytest`
  - `python -m unittest discover`
- Restricted Docker execution with captured stdout, stderr, exit code,
  duration, timestamp, timeout state, and errors.
- JSON reports for successful, failed, and unsupported repositories.

ReproBot does **not** currently install project dependencies, modify project
files, repair failing code, retry commands, enable container networking, or
provide a web dashboard.

## Architecture

The implementation is split into small modules:

```text
src/reprobot/
├── cli.py             # argument parsing and end-to-end workflow
├── detector.py        # non-executing repository inspection
├── docker_runner.py   # restricted Docker command execution
├── models.py          # report and detection data models
├── __main__.py        # python -m reprobot entry point
└── __init__.py
```

The workflow is:

```text
local path
    ↓
detector
    ↓
test-command selection
    ↓
restricted Docker runner
    ↓
structured ExecutionReport
```

Detection does not execute project code. Only the selected test command is
passed to the Docker runner, and the target repository is mounted read-only.

## Prerequisites

- Python 3.11 or newer.
- Git available on `PATH`.
- Docker Desktop or Docker Engine available on `PATH` and running.
- Permission to run Docker containers.

The runner uses the immutable Docker image reference below:

```text
python@sha256:2199a62885a12290dc9c5be3ca0681d367576ab7bf037da120e564723292a2f0
```

This digest was verified locally for the `linux/amd64` image created from
`python:3.12.8-slim-bookworm`. Docker must be able to obtain this image before
an end-to-end run. ReproBot itself does not pull images automatically.

## Installation

From a clean checkout, create an isolated development environment and install
the package with its pinned test dependency:

```bash
python -m venv .venv
```

On macOS/Linux:

```bash
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

On Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

The project declares no runtime Python dependencies. Its development test
dependency is pinned to `pytest==8.3.5`; the build backend is pinned to
`setuptools==75.8.0`. The Python interpreter itself is constrained to
`>=3.11`, rather than to one patch release.

This is a pinned project configuration, not a complete transitive dependency
lockfile: pytest's own dependencies are resolved by pip. Fully locked
development environments are a remaining release-hardening task.

## CLI usage

After installation, inspect and test a local repository:

```bash
python -m reprobot PATH_TO_REPOSITORY
```

Without `--report`, the complete JSON report is printed to standard output.

To save the report to a file:

```bash
python -m reprobot PATH_TO_REPOSITORY --report reports/reprobot-report.json
```

When `--report` is supplied, the CLI prints a short status and the report
path. The JSON file remains the authoritative detailed result.

For an uninstalled source checkout, use the source directory explicitly:

```bash
PYTHONPATH=src python -m reprobot PATH_TO_REPOSITORY --report report.json
```

On Windows PowerShell, the equivalent is:

```powershell
$env:PYTHONPATH = "src"
python -m reprobot PATH_TO_REPOSITORY --report report.json
```

Show command help with:

```bash
python -m reprobot --help
```

## Detection and command selection

ReproBot first checks that the supplied directory is a valid local Git
repository. It then inspects files without importing or executing the target
project.

Recognized Python indicators include:

- `pyproject.toml`
- `setup.py`
- `setup.cfg`
- `requirements*.txt`
- Python source files

Likely tests are identified from files named `test_*.py` or `*_test.py` and
from their imports/configuration. The current command-selection rules are:

1. Select `python -m pytest` when pytest configuration or pytest imports are
   detected.
2. Otherwise select `python -m unittest discover` when unittest evidence is
   detected.
3. Refuse to guess when tests exist but no supported framework is identified.
4. Report the repository as unsupported when no likely tests are found.

No dependency installation occurs. Consequently, a pytest project must already
have pytest available in the selected Docker image for its test command to
pass. The current pinned Python image does not receive packages from the
target repository during this milestone.

## JSON reports and exit codes

Reports use schema version `1` and include:

- Overall status: `success`, `failed`, or `unsupported`.
- Repository path, name, and Git validation result.
- Detected Python markers, dependency files, lockfiles, test configuration,
  frameworks, and whether tests appear to exist.
- Every attempted command, including its arguments, exit code, stdout, stderr,
  start timestamp, duration, timeout flag, and error.
- Clear reasons for unsupported input or execution failures.

The CLI exits with:

| Code | Meaning |
| ---: | --- |
| `0` | The selected test command completed with exit code `0`. |
| `1` | Execution was attempted but Docker or the test command failed. |
| `2` | The repository is unsupported, or a CLI/report-output error occurred. |

## Isolation and security

Target commands are never executed directly on the host. The Docker runner:

- Mounts only the explicitly selected repository, read-only, at `/workspace`.
- Uses `/workspace` as the container working directory.
- Disables container networking with `--network none`.
- Drops all Linux capabilities.
- Enables `no-new-privileges`.
- Uses a read-only container filesystem.
- Provides only a small restricted `/tmp` tmpfs.
- Applies one CPU, 512 MiB memory, and a 128-process limit.
- Enforces a 120-second per-command timeout by default.
- Uses a temporary named container and attempts cleanup after every run.
- Does not mount the Docker socket, home directories, credentials, or host
  environment variables.
- Does not invoke a host shell for the Docker command.

The repository itself is still untrusted input. Docker is an isolation boundary,
not a complete security guarantee; keep Docker updated and do not run ReproBot
with broader host permissions than necessary.

## Testing and integration checks

Run the unit test suite:

```bash
python -m pytest -q
```

Run the syntax/bytecode compilation check:

```bash
python -m compileall -q src tests
```

The unit tests use temporary local Git fixtures and mock Docker subprocesses,
so they do not require network access or Docker. They cover report
serialization, detection, command construction, timeout/error handling, and
CLI workflow behavior.

There is no permanent external-repository integration test. A real Docker
check should use a controlled local fixture and an already available image,
for example a temporary repository containing a standard-library unittest.
The check must be reported as skipped when Docker or the pinned image is not
available; a mocked runner is not evidence of a successful Docker integration
run.

## Limitations and next steps

This release deliberately excludes:

- Dependency installation or lockfile-driven environment creation.
- Network-enabled execution or an implicit image pull.
- Automatic code modification, repair, retries, or autonomous loops.
- Test-framework support beyond the current pytest/unittest detection.
- Multi-language repositories.
- A dashboard, persistent service, or hosted execution environment.

Before a public submission, the remaining release tasks are to review the
Docker image supply-chain policy, decide how dependency installation should be
made reproducible and optionally offline, add a maintained Docker integration
fixture/check, and review the staged Git diff for the intended release.
