import subprocess
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from copier_template import main
from copier_template.config import ANSWERS_FILE

runner = CliRunner()


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def init_repo(path: Path) -> None:
    git(path, "init", "-q", "-b", "main")
    git(path, "config", "user.email", "test@example.com")
    git(path, "config", "user.name", "test")
    git(path, "config", "commit.gpgsign", "false")


def commit(path: Path, message: str) -> None:
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", message)


class FakePyProject:
    def ensure(self, *a):
        return self


@pytest.fixture
def template(tmp_path, monkeypatch):
    root = tmp_path / "template"
    (root / "template").mkdir(parents=True)
    (root / "src" / "copier_template").mkdir(parents=True)
    (root / "copier.yml").write_text(
        f"_subdirectory: template\n_answers_file: {ANSWERS_FILE}\n", encoding="utf-8"
    )
    (root / "template" / "{{ _copier_conf.answers_file }}.jinja").write_text(
        "{{ _copier_answers|to_nice_yaml }}", encoding="utf-8"
    )
    (root / "template" / "hello.txt").write_text("v1\n", encoding="utf-8")
    init_repo(root)
    commit(root, "v1")
    git(root, "tag", "v0.1.0")
    monkeypatch.setattr(
        main, "__file__", str(root / "src" / "copier_template" / "main.py")
    )
    monkeypatch.setattr(main, "prepare_pyproject", lambda cwd, *a: None)
    return root


@pytest.fixture
def published(tmp_path, template):
    clone = tmp_path / "published"
    git(tmp_path, "clone", "-q", str(template), str(clone))
    return clone


@pytest.fixture
def project(tmp_path, published):
    dst = tmp_path / "project"
    main.copier.run_copy(
        str(published), str(dst), unsafe=True, answers_file=ANSWERS_FILE, quiet=True
    )
    init_repo(dst)
    commit(dst, "generated")
    return dst


@pytest.mark.slow
def test_update_local_uses_uncommitted_template_changes(template, published, project):
    answers = (project / ANSWERS_FILE).read_text(encoding="utf-8")
    assert yaml.safe_load(answers)["_src_path"] == str(published)
    (template / "template" / "hello.txt").write_text("v2\n", encoding="utf-8")

    result = runner.invoke(main.app, ["update", str(project), "--local"])

    assert result.exit_code == 0, result.output
    assert (project / "hello.txt").read_text(encoding="utf-8") == "v2\n"
    assert (project / ANSWERS_FILE).read_text(encoding="utf-8") == answers
    assert yaml.safe_load(answers)["_commit"] == "v0.1.0"


@pytest.mark.slow
def test_init_local_then_official_update(monkeypatch, tmp_path, template, published):
    monkeypatch.setattr(main, "COPIER_REPO", str(published))
    monkeypatch.setattr(main, "pyproject", lambda cwd: FakePyProject())
    (template / "template" / "hello.txt").write_text("local\n", encoding="utf-8")
    dst = tmp_path / "fresh"

    result = runner.invoke(main.app, ["init", str(dst), "--local"])

    assert result.exit_code == 0, result.output
    assert (dst / "hello.txt").read_text(encoding="utf-8") == "local\n"
    answers = yaml.safe_load((dst / ANSWERS_FILE).read_text(encoding="utf-8"))
    assert answers["_src_path"] == str(published)
    assert answers["_commit"] == "v0.1.0"

    init_repo(dst)
    commit(dst, "generated")
    git(template, "checkout", "--", ".")
    (template / "template" / "added.txt").write_text("new\n", encoding="utf-8")
    commit(template, "v2")
    git(template, "tag", "v0.2.0")
    git(published, "pull", "-q", "--tags", "origin", "main")

    result = runner.invoke(main.app, ["update", str(dst), "--official"])

    assert result.exit_code == 0, result.output
    assert (dst / "added.txt").read_text(encoding="utf-8") == "new\n"
    answers = yaml.safe_load((dst / ANSWERS_FILE).read_text(encoding="utf-8"))
    assert answers["_commit"] == "v0.2.0"
