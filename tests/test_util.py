import json
import subprocess

import pytest
import tomlkit
import typer
from pydantic import Secret, TypeAdapter, ValidationError

from copier_template import util
from copier_template.util import (
    EntryPoint,
    MemberPath,
    PackageName,
    ProjectTable,
    PyProject,
    TerraformModule,
    TerraformOutput,
    TerraformOutputError,
    e,
    sh,
)

OUTPUTS = json.dumps(
    {
        "config": {
            "value": {"a": 1},
            "sensitive": False,
            "type": ["object", {"a": "number"}],
        },
        "token": {"value": "s3cret", "sensitive": True, "type": "string"},
    }
)


def completed(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args="", returncode=returncode, stdout=stdout, stderr=""
    )


@pytest.fixture
def tf_dir(tmp_path):
    d = tmp_path / "prod"
    d.mkdir()
    return d


@pytest.fixture
def fake_sh(monkeypatch):
    calls: list[tuple[str, dict]] = []
    responses: dict[str, subprocess.CompletedProcess] = {}

    def fake(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return responses.get(cmd, completed())

    monkeypatch.setattr(util, "sh", fake)
    fake.calls = calls
    fake.responses = responses
    return fake


@pytest.fixture
def module(tf_dir, fake_sh):
    fake_sh.responses["terraform output -json -no-color"] = completed(OUTPUTS)
    return TerraformModule(cwd=tf_dir, tf_vars={})


class TestE:
    def test_wraps_errors_as_exit(self, monkeypatch, capsys):
        monkeypatch.delenv("DEBUG", raising=False)

        @e
        def boom():
            raise RuntimeError("bad thing")

        with pytest.raises(typer.Exit) as exc:
            boom()
        assert exc.value.exit_code == 1
        assert "bad thing" in capsys.readouterr().err

    def test_debug_reraises(self, monkeypatch):
        monkeypatch.setenv("DEBUG", "1")

        @e
        def boom():
            raise RuntimeError("bad thing")

        with pytest.raises(RuntimeError):
            boom()

    def test_exit_passes_through(self):
        @e
        def stop():
            raise typer.Exit(3)

        with pytest.raises(typer.Exit) as exc:
            stop()
        assert exc.value.exit_code == 3


class TestSh:
    def test_captures_output(self):
        assert sh("echo hi", silent=True).stdout.strip() == "hi"

    def test_failure_exits_with_code(self):
        with pytest.raises(typer.Exit) as exc:
            sh("exit 3", silent=True)
        assert exc.value.exit_code == 3

    def test_check_false_returns(self):
        assert sh("exit 3", silent=True, check=False).returncode == 3

    def test_merges_env(self, monkeypatch):
        seen = {}

        def fake_run(cmd, **kwargs):
            seen.update(kwargs["env"])
            return completed()

        monkeypatch.setattr(subprocess, "run", fake_run)
        monkeypatch.setenv("BASE", "1")
        sh("anything", env={"EXTRA": "2"})
        assert seen["BASE"] == "1"
        assert seen["EXTRA"] == "2"


class TestTerraformOutput:
    def test_sensitive_is_wrapped(self):
        out = TerraformOutput(value="s3cret", sensitive=True, type="string")
        assert isinstance(out.value, Secret)
        assert "s3cret" not in repr(out)
        assert out.get_secret_value() == "s3cret"

    def test_plain_value_unchanged(self):
        out = TerraformOutput(value={"a": 1}, sensitive=False, type="object")
        assert out.get_secret_value() == {"a": 1}


class TestTerraformModule:
    def test_rejects_file_as_cwd(self, tmp_path):
        f = tmp_path / "main.tf"
        f.touch()
        with pytest.raises(ValidationError):
            TerraformModule(cwd=f, tf_vars={})

    def test_rejects_bad_var_names(self, tf_dir):
        with pytest.raises(ValidationError, match="NOT_TF"):
            TerraformModule(cwd=tf_dir, tf_vars={"NOT_TF": "x"})

    def test_outputs_parsed_and_cached(self, module, fake_sh):
        assert module.get_output("config") == {"a": 1}
        assert module.get_output("token") == "s3cret"
        output_calls = [c for c, _ in fake_sh.calls if c.startswith("terraform output")]
        assert len(output_calls) == 1

    def test_missing_key_masks_secrets(self, module):
        with pytest.raises(TerraformOutputError) as exc:
            module.get_output("nope")
        assert "config" in str(exc.value)
        assert "s3cret" not in str(exc.value)

    def test_failed_output_is_empty(self, tf_dir, fake_sh):
        fake_sh.responses["terraform output -json -no-color"] = completed(returncode=1)
        m = TerraformModule(cwd=tf_dir, tf_vars={})
        assert m.outputs == {}
        with pytest.raises(TerraformOutputError, match="applied"):
            m.get_output("config")

    def test_apply_runs_in_order_and_clears_cache(self, module, fake_sh):
        module.outputs
        module.apply()
        module.outputs
        cmds = [c for c, _ in fake_sh.calls]
        assert cmds == [
            "terraform output -json -no-color",
            "terraform init -upgrade",
            "terraform plan",
            "terraform apply -auto-approve",
            "terraform output -json -no-color",
        ]

    def test_apply_without_auto_approve(self, module, fake_sh):
        module.apply(a=False)
        assert fake_sh.calls[-1][0] == "terraform apply"

    def test_env_values_are_strings(self, tf_dir, fake_sh):
        m = TerraformModule(
            cwd=tf_dir,
            tf_vars={
                "TF_VAR_token": Secret("x"),
                "TF_VAR_list": ["a"],
                "TF_VAR_name": "n",
            },
        )
        m.tf("version")
        env = fake_sh.calls[-1][1]["env"]
        assert env["TF_VAR_token"] == "x"
        assert env["TF_VAR_list"] == '["a"]'
        assert env["TF_VAR_name"] == "n"
        assert all(isinstance(v, str) for v in env.values())


class TestTypes:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("My-Project", "my_project"),
            (" orders ", "orders"),
            ("OrdersAPI", "orders_api"),
        ],
    )
    def test_package_name(self, raw, expected):
        assert TypeAdapter(PackageName).validate_python(raw) == expected

    def test_package_name_rejects_leading_digit(self):
        with pytest.raises(ValidationError):
            TypeAdapter(PackageName).validate_python("1orders")

    @pytest.mark.parametrize("value", ["pkg.mod:func", "pkg:obj.attr"])
    def test_entry_point_valid(self, value):
        assert TypeAdapter(EntryPoint).validate_python(value) == value

    @pytest.mark.parametrize("value", ["pkg.mod", "pkg:", ":func"])
    def test_entry_point_invalid(self, value):
        with pytest.raises(ValidationError):
            TypeAdapter(EntryPoint).validate_python(value)

    def test_member_path_uses_forward_slashes(self):
        assert TypeAdapter(MemberPath).validate_python("libs\\core") == "libs/core"

    def test_project_table_allows_extra(self):
        t = ProjectTable.model_validate({"name": "My-App", "dependencies": ["x"]})
        assert t.package == "my_app"
        assert t.model_extra == {"dependencies": ["x"]}


class TestPyProject:
    def test_create(self, tmp_path):
        pp = PyProject(cwd=tmp_path).create("My-Project")
        assert pp.project.name == "my_project"
        assert (tmp_path / "src" / "my_project" / "__init__.py").is_file()

    def test_doc_missing_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            PyProject(cwd=tmp_path).doc

    def test_ensure_existing_does_not_prompt(self, tmp_path, monkeypatch):
        PyProject(cwd=tmp_path).create("app")
        monkeypatch.setattr(typer, "prompt", lambda *a, **k: pytest.fail("prompted"))
        assert PyProject(cwd=tmp_path).ensure().project.name == "app"

    def test_ensure_prompts_when_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(typer, "prompt", lambda *a, **k: "New App")
        assert PyProject(cwd=tmp_path).ensure().project.name == "new_app"

    def test_ensure_uses_given_name(self, tmp_path):
        assert PyProject(cwd=tmp_path).ensure("given").project.name == "given"

    def test_add_workspace_is_idempotent(self, tmp_path):
        pp = PyProject(cwd=tmp_path).create("app")
        pp.add_workspace({"core": "libs/core"}).add_workspace(
            {"core": "libs/core"}
        ).save()
        data = tomlkit.parse((tmp_path / "pyproject.toml").read_text()).unwrap()
        assert data["tool"]["uv"]["workspace"]["members"] == ["libs/core"]
        assert data["tool"]["uv"]["sources"]["core"] == {"workspace": True}

    def test_add_workspace_keeps_existing(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "app"\n\n'
            "# keep me\n"
            '[tool.uv.workspace]\nmembers = ["libs/old"]\n\n'
            '[tool.uv.sources]\ncore = { path = "../core" }\n'
        )
        PyProject(cwd=tmp_path).add_workspace(
            {"core": "libs/core", "new": "libs/new"}
        ).save()
        text = (tmp_path / "pyproject.toml").read_text()
        data = tomlkit.parse(text).unwrap()
        assert data["tool"]["uv"]["workspace"]["members"] == [
            "libs/old",
            "libs/core",
            "libs/new",
        ]
        assert data["tool"]["uv"]["sources"]["core"] == {"path": "../core"}
        assert data["tool"]["uv"]["sources"]["new"] == {"workspace": True}
        assert "# keep me" in text

    def test_add_scripts(self, tmp_path):
        pp = PyProject(cwd=tmp_path).create("app")
        pp.add_scripts({"app": "app.__main__:cli"}).save()
        assert pp.reload().project.scripts == {"app": "app.__main__:cli"}

    def test_add_scripts_rejects_bad_target(self, tmp_path):
        pp = PyProject(cwd=tmp_path).create("app")
        with pytest.raises(ValidationError):
            pp.add_scripts({"app": "no_colon"})

    def test_empty_inputs_change_nothing(self, tmp_path):
        pp = PyProject(cwd=tmp_path).create("app")
        before = pp.path.read_text()
        pp.add_workspace({}).add_scripts({}).save()
        assert pp.path.read_text() == before

    def test_reload_sees_external_change(self, tmp_path):
        pp = PyProject(cwd=tmp_path).create("app")
        assert pp.project.name == "app"
        pp.path.write_text('[project]\nname = "renamed"\n')
        assert pp.project.name == "app"
        assert pp.reload().project.name == "renamed"

    def test_virtual_root_has_no_project(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            '[tool.uv.workspace]\nmembers = ["a"]\n'
        )
        assert PyProject(cwd=tmp_path).project is None
