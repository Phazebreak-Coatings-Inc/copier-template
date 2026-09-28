import subprocess
from pathlib import Path

import pytest
import typer
import yaml
from typer.testing import CliRunner

from copier_template import main
from copier_template.config import ANSWERS_FILE, COPIER_REPO

runner = CliRunner()

PUBLISHED = {"_commit": "v0.3.1", "_src_path": COPIER_REPO, "project_name": "demo"}


def write_answers(cwd: Path, answers: dict) -> Path:
    path = cwd / ANSWERS_FILE
    path.write_text(yaml.safe_dump(answers, sort_keys=False), encoding="utf-8")
    return path


def read_answers(cwd: Path) -> dict:
    return yaml.safe_load((cwd / ANSWERS_FILE).read_text(encoding="utf-8"))


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def git_repo(path: Path) -> None:
    git(path, "init", "-q", "-b", "main")
    git(path, "config", "user.email", "test@example.com")
    git(path, "config", "user.name", "test")
    git(path, "config", "commit.gpgsign", "false")
    (path / "file.txt").write_text("x", encoding="utf-8")
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "init")


@pytest.fixture
def template(tmp_path):
    root = tmp_path / "template"
    (root / "src" / "copier_template").mkdir(parents=True)
    (root / "copier.yml").write_text("_subdirectory: template\n", encoding="utf-8")
    return root


@pytest.fixture
def local_checkout(monkeypatch, template):
    monkeypatch.setattr(
        main, "__file__", str(template / "src" / "copier_template" / "main.py")
    )
    return template


@pytest.fixture
def project(tmp_path):
    d = tmp_path / "project"
    d.mkdir()
    return d


@pytest.fixture
def repaired(monkeypatch):
    calls: list[Path] = []
    monkeypatch.setattr(main, "prepare_pyproject", lambda cwd, *a: calls.append(cwd))
    return calls


@pytest.fixture
def ensured(monkeypatch):
    calls: list[Path] = []

    class Fake:
        def __init__(self, cwd):
            self.cwd = cwd

        def ensure(self, *a):
            calls.append(self.cwd)
            return self

    monkeypatch.setattr(main, "pyproject", Fake)
    return calls


@pytest.fixture
def copied(monkeypatch):
    calls: list[dict] = []

    def fake(src, dst, **kwargs):
        calls.append({"src": src, "dst": dst, **kwargs})
        write_answers(Path(dst), {**PUBLISHED, "_src_path": src, "_commit": "tmp"})

    monkeypatch.setattr(main.copier, "run_copy", fake)
    return calls


@pytest.fixture
def worker(monkeypatch):
    class FakeWorker:
        calls: list[dict] = []
        error: Exception | None = None

        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def run_update(self):
            FakeWorker.calls.append(self.kwargs)
            dst = self.kwargs["dst_path"]
            if self.kwargs["src_path"]:
                write_answers(
                    dst,
                    {
                        **PUBLISHED,
                        "_src_path": self.kwargs["src_path"],
                        "_commit": "tmp",
                    },
                )
            if FakeWorker.error:
                raise FakeWorker.error

    FakeWorker.calls = []
    FakeWorker.error = None
    monkeypatch.setattr(main, "Worker", FakeWorker)
    return FakeWorker


class TestValidateTemplateRoot:
    def test_accepts_template_root(self, template):
        assert main.validate_template_root(str(template)) == template

    def test_exits_outside_template_root(self, tmp_path):
        with pytest.raises(typer.Exit):
            main.validate_template_root(tmp_path)


class TestLocalTemplate:
    def test_returns_checkout_root(self, local_checkout):
        assert main.local_template() == local_checkout.resolve()

    def test_rejects_installed_package(self, monkeypatch, tmp_path):
        site = tmp_path / "site-packages" / "copier_template" / "main.py"
        monkeypatch.setattr(main, "__file__", str(site))
        with pytest.raises(typer.BadParameter):
            main.local_template()


class TestSetAnswers:
    def test_only_changes_given_keys(self, project):
        write_answers(project, PUBLISHED)
        main.set_answers(project, _src_path="/local", _commit="v0.1.12")
        assert read_answers(project) == {
            **PUBLISHED,
            "_src_path": "/local",
            "_commit": "v0.1.12",
        }

    def test_keeps_header_comment(self, project):
        path = project / ANSWERS_FILE
        path.write_text(
            "# managed by copier-template, do not edit\n"
            + yaml.safe_dump(PUBLISHED, sort_keys=False),
            encoding="utf-8",
        )
        main.set_answers(project, _commit="v0.1.12")
        text = path.read_text(encoding="utf-8")
        assert text.startswith("# managed by copier-template, do not edit\n")
        assert read_answers(project)["_commit"] == "v0.1.12"


class TestLatestTag:
    def test_returns_nearest_tag(self, tmp_path):
        git_repo(tmp_path)
        git(tmp_path, "tag", "v1.0.0")
        (tmp_path / "later.txt").write_text("x", encoding="utf-8")
        git(tmp_path, "add", "-A")
        git(tmp_path, "commit", "-q", "-m", "later")
        assert main.latest_tag(tmp_path) == "v1.0.0"

    def test_untagged_repo(self, tmp_path):
        git_repo(tmp_path)
        assert main.latest_tag(tmp_path) is None

    def test_not_a_repo(self, tmp_path):
        assert main.latest_tag(tmp_path) is None


class TestRestoredAnswers:
    def test_restores_original_text(self, project, template):
        path = write_answers(project, PUBLISHED)
        original = path.read_text(encoding="utf-8")
        with main.restored_answers(project, template):
            path.write_text("changed", encoding="utf-8")
        assert path.read_text(encoding="utf-8") == original

    def test_restores_on_error(self, project, template):
        path = write_answers(project, PUBLISHED)
        original = path.read_text(encoding="utf-8")
        with pytest.raises(RuntimeError), main.restored_answers(project, template):
            path.write_text("changed", encoding="utf-8")
            raise RuntimeError
        assert path.read_text(encoding="utf-8") == original

    def test_new_file_points_at_published_tag(self, monkeypatch, project, template):
        monkeypatch.setattr(main, "latest_tag", lambda t: "v0.1.12")
        with main.restored_answers(project, template):
            write_answers(
                project, {**PUBLISHED, "_src_path": "/local", "_commit": "tmp"}
            )
        assert read_answers(project)["_src_path"] == COPIER_REPO
        assert read_answers(project)["_commit"] == "v0.1.12"

    def test_new_file_without_tag_warns(self, monkeypatch, project, template, capsys):
        monkeypatch.setattr(main, "latest_tag", lambda t: None)
        with main.restored_answers(project, template):
            write_answers(
                project, {**PUBLISHED, "_src_path": "/local", "_commit": "tmp"}
            )
        assert read_answers(project)["_src_path"] == COPIER_REPO
        assert read_answers(project)["_commit"] == "tmp"
        assert "No tag found" in capsys.readouterr().err

    def test_no_file_is_left_alone(self, project, template):
        with main.restored_answers(project, template):
            pass
        assert not (project / ANSWERS_FILE).exists()


class TestRepair:
    def test_prepares_pyproject(self, project, repaired):
        result = runner.invoke(main.app, ["repair", str(project)])
        assert result.exit_code == 0, result.output
        assert repaired == [project]


class TestInit:
    def test_official(self, project, ensured, copied, repaired):
        result = runner.invoke(main.app, ["init", str(project)])
        assert result.exit_code == 0, result.output
        assert ensured == [project]
        assert copied[0]["src"] == COPIER_REPO
        assert copied[0]["vcs_ref"] is None
        assert copied[0]["answers_file"] == ANSWERS_FILE
        assert copied[0]["defaults"] is False
        assert repaired == [project]

    def test_local(
        self, monkeypatch, project, local_checkout, ensured, copied, repaired
    ):
        monkeypatch.setattr(main, "latest_tag", lambda t: "v0.1.12")
        result = runner.invoke(main.app, ["init", str(project), "--local"])
        assert result.exit_code == 0, result.output
        assert copied[0]["src"] == str(local_checkout.resolve())
        assert copied[0]["vcs_ref"] == "HEAD"
        assert read_answers(project)["_src_path"] == COPIER_REPO
        assert read_answers(project)["_commit"] == "v0.1.12"
        assert repaired == [project]

    def test_local_from_installed_package_fails(
        self, monkeypatch, project, tmp_path, ensured, copied, repaired
    ):
        monkeypatch.setattr(main, "__file__", str(tmp_path / "a" / "b" / "main.py"))
        result = runner.invoke(main.app, ["init", str(project), "--local"])
        assert result.exit_code == 1
        assert "--local needs" in result.output
        assert copied == []
        assert repaired == []

    def test_defaults(self, project, ensured, copied, repaired):
        result = runner.invoke(main.app, ["init", str(project), "--defaults"])
        assert result.exit_code == 0, result.output
        assert copied[0]["defaults"] is True


class TestUpdate:
    def test_defaults(self, project, worker, repaired):
        write_answers(project, PUBLISHED)
        result = runner.invoke(main.app, ["update", str(project), "--defaults"])
        assert result.exit_code == 0, result.output
        assert worker.calls[0]["defaults"] is True

    def test_official(self, project, worker, repaired):
        write_answers(project, PUBLISHED)
        result = runner.invoke(main.app, ["update", str(project)])
        assert result.exit_code == 0, result.output
        call = worker.calls[0]
        assert call["src_path"] is None
        assert call["vcs_ref"] is None
        assert call["dst_path"] == project
        assert call["answers_file"] == Path(ANSWERS_FILE)
        assert call["overwrite"] is True
        assert call["conflict"] == "inline"
        assert call["unsafe"] is True
        assert call["skip_tasks"] is True
        assert call["defaults"] is False
        assert repaired == [project]

    def test_official_flag_matches_default(self, project, worker, repaired):
        write_answers(project, PUBLISHED)
        result = runner.invoke(main.app, ["update", str(project), "--official"])
        assert result.exit_code == 0, result.output
        assert worker.calls[0]["src_path"] is None

    def test_local(self, project, local_checkout, worker, repaired):
        path = write_answers(project, PUBLISHED)
        original = path.read_text(encoding="utf-8")
        result = runner.invoke(main.app, ["update", str(project), "--local"])
        assert result.exit_code == 0, result.output
        assert worker.calls[0]["src_path"] == str(local_checkout.resolve())
        assert worker.calls[0]["vcs_ref"] == "HEAD"
        assert path.read_text(encoding="utf-8") == original
        assert repaired == [project]

    def test_local_restores_answers_on_error(
        self, project, local_checkout, worker, repaired
    ):
        path = write_answers(project, PUBLISHED)
        original = path.read_text(encoding="utf-8")
        worker.error = RuntimeError("Destination repository is dirty")
        result = runner.invoke(main.app, ["update", str(project), "--local"])
        assert result.exit_code == 1
        assert "Destination repository is dirty" in result.output
        assert path.read_text(encoding="utf-8") == original
        assert repaired == []

    def test_local_does_not_touch_answers_before_update(
        self, project, local_checkout, monkeypatch, repaired
    ):
        path = write_answers(project, PUBLISHED)
        original = path.read_text(encoding="utf-8")
        seen: list[str] = []

        def fake_run_update(cwd, template, defaults):
            seen.append(path.read_text(encoding="utf-8"))

        monkeypatch.setattr(main, "run_update", fake_run_update)
        result = runner.invoke(main.app, ["update", str(project), "--local"])
        assert result.exit_code == 0, result.output
        assert seen == [original]


class TestExample:
    def test_exits_outside_template_root(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(main.app, ["example"])
        assert result.exit_code == 1
        assert "Run from the template repo root." in result.output
