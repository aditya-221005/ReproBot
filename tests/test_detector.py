import subprocess

from reprobot.detector import detect_repository


def initialize_git_repository(path) -> None:
    subprocess.run(
        ["git", "init", "--quiet", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )


def test_detects_python_project_dependencies_tests_and_supported_lockfile(tmp_path) -> None:
    repository = tmp_path / "passing-project"
    repository.mkdir()
    initialize_git_repository(repository)
    (repository / "pyproject.toml").write_text(
        "[project]\nname = 'passing-project'\n\n[tool.pytest.ini_options]\n",
        encoding="utf-8",
    )
    (repository / "requirements-dev.txt").write_text("pytest==8.3.5\n", encoding="utf-8")
    (repository / "requirements.lock").write_text("pytest==8.3.5\n", encoding="utf-8")
    tests = repository / "tests"
    tests.mkdir()
    (tests / "test_example.py").write_text(
        "def test_example():\n    assert True\n", encoding="utf-8"
    )

    result = detect_repository(repository)

    assert result.supported is True
    assert result.repository.git_repository is True
    assert result.python_project is True
    assert result.dependency_files == ["pyproject.toml", "requirements-dev.txt"]
    assert [lockfile.path for lockfile in result.lockfiles] == ["requirements.lock"]
    assert result.lockfiles[0].supported is True
    assert result.test_configuration == ["pyproject.toml"]
    assert result.test_frameworks == ["pytest"]
    assert result.tests_exist is True
    assert result.reasons == []


def test_recognizes_but_rejects_unsupported_lockfile_without_guessing(tmp_path) -> None:
    repository = tmp_path / "poetry-project"
    repository.mkdir()
    initialize_git_repository(repository)
    (repository / "pyproject.toml").write_text(
        "[tool.poetry]\nname = 'poetry-project'\n", encoding="utf-8"
    )
    (repository / "poetry.lock").write_text("# lockfile\n", encoding="utf-8")

    result = detect_repository(repository)

    assert result.supported is False
    assert result.lockfiles[0].format == "Poetry lockfile"
    assert result.lockfiles[0].supported is False
    assert "not supported for execution" in result.lockfiles[0].reason
    assert any("poetry.lock" in reason for reason in result.reasons)


def test_reports_non_git_directory_as_unsupported(tmp_path) -> None:
    repository = tmp_path / "not-a-repository"
    repository.mkdir()
    (repository / "requirements.txt").write_text("requests==2.32.3\n", encoding="utf-8")

    result = detect_repository(repository)

    assert result.supported is False
    assert result.repository.git_repository is False
    assert any("not a valid local Git repository" in reason for reason in result.reasons)


def test_reports_non_python_git_repository_as_unsupported(tmp_path) -> None:
    repository = tmp_path / "documentation-only"
    repository.mkdir()
    initialize_git_repository(repository)
    (repository / "README.md").write_text("Documentation only\n", encoding="utf-8")

    result = detect_repository(repository)

    assert result.supported is False
    assert result.repository.git_repository is True
    assert result.python_project is False
    assert "No supported Python project markers were found." in result.reasons


def test_detects_unittest_and_test_existence_without_framework_config(tmp_path) -> None:
    repository = tmp_path / "unittest-project"
    repository.mkdir()
    initialize_git_repository(repository)
    (repository / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repository / "test_app.py").write_text(
        "import unittest\n\nclass AppTest(unittest.TestCase):\n    pass\n",
        encoding="utf-8",
    )

    result = detect_repository(repository)

    assert result.python_project is True
    assert result.tests_exist is True
    assert result.test_frameworks == ["unittest"]
