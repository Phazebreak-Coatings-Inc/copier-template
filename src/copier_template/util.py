import functools
import json
import os
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, Self, cast

import inflection
import tomlkit
import typer
from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    JsonValue,
    PrivateAttr,
    Secret,
    StringConstraints,
    model_validator,
    validate_call,
)
from tomlkit import TOMLDocument
from tomlkit.items import Table


def e(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except typer.Exit, typer.Abort:
            raise
        except Exception as exc:
            if os.environ.get("DEBUG"):
                raise
            typer.secho(str(exc), err=True, fg=typer.colors.RED)
            raise typer.Exit(1)

    return wrapper


def sh(
    cmd: str, silent=False, check=True, env: dict[str, Any] = {}, **kwargs
) -> subprocess.CompletedProcess:
    if silent:
        kwargs.setdefault("stdout", subprocess.PIPE)
        kwargs.setdefault("stderr", subprocess.PIPE)
        kwargs.setdefault("text", True)
    kwargs.setdefault("encoding", "utf-8")
    kwargs.setdefault("errors", "replace")
    try:
        return subprocess.run(
            cmd,
            shell=True,
            check=check,
            env={**os.environ, **(env or {})},
            **kwargs,
        )
    except subprocess.CalledProcessError as e:
        if not silent:
            typer.secho(f"\nFailed: {cmd}", fg=typer.colors.BRIGHT_RED, err=True)
            if output := (e.stderr or e.stdout):
                typer.secho(output.rstrip(), fg=typer.colors.RED, err=True)
        raise typer.Exit(e.returncode) from None


def is_terraform_dir(p: Path | str) -> Path:
    if isinstance(p, str):
        p = Path(p)
    if p.is_file():
        raise ValueError(f"The following is not a terraform directory: {p}")
    return p


TerraformDir = Annotated[Path, BeforeValidator(is_terraform_dir)]


class TerraformOutputError(Exception): ...


class TerraformOutput(BaseModel):
    value: JsonValue | Secret[JsonValue]
    sensitive: bool
    type: JsonValue

    @model_validator(mode="after")
    def wrap_sensitive(self):
        if self.sensitive and not isinstance(self.value, Secret):
            self.value = Secret(self.value)
        return self

    def get_secret_value(self):
        if isinstance(self.value, Secret):
            return self.value.get_secret_value()
        return self.value  # if on accident


def are_valid_tf_vars(t: dict[str, JsonValue | Secret[JsonValue]]) -> TFVars:
    if bad := sorted(k for k in t if not k.startswith("TF_")):
        raise ValueError(f"Keys passed to tf vars must start with 'TF_': {bad}")
    return t


TFVars = Annotated[
    dict[str, JsonValue | Secret[JsonValue]], BeforeValidator(are_valid_tf_vars)
]


class TerraformModule[OutputsShape: Mapping = Mapping](BaseModel):
    tf_vars: TFVars
    cwd: TerraformDir
    _outputs_cache: dict[str, TerraformOutput] | None = PrivateAttr(default=None)

    def tf(self, cmd: str, check: bool = True, silent: bool = False, **kwargs):
        return sh(
            f"terraform {cmd}",
            cwd=self.cwd,
            check=check,
            silent=silent,
            text=True,
            env={**os.environ, **self.tf_vars},
            **kwargs,
        )

    def plan(self) -> subprocess.CompletedProcess:
        self.tf("init -upgrade")
        return self.tf("plan")

    def apply(self, a: bool = True):
        """
        param a: auto-approve
        """
        self.plan()
        try:
            self.tf("apply -auto-approve" if a else "apply")
        finally:
            self._outputs_cache = None

    @property
    def outputs(self) -> dict[str, TerraformOutput]:
        if self._outputs_cache is None:
            r = self.tf("output -json -no-color", check=False, silent=True)
            self._outputs_cache = (
                {}
                if r.returncode != 0 or not (r.stdout or "").strip()
                else {
                    k: TerraformOutput.model_validate(v)
                    for k, v in json.loads(r.stdout).items()
                }
            )
        return self._outputs_cache

    def get_output(self, key: str) -> JsonValue:
        outputs = self.outputs
        if key not in outputs:
            if outputs:
                masked = {
                    k: "**********" if isinstance(v.value, Secret) else v.value
                    for k, v in outputs.items()
                }
                detail = f"Available: {json.dumps(masked, indent=2)}"
            else:
                detail = "No outputs are available. Has this been applied yet?"
            raise TerraformOutputError(f"No terraform output for key '{key}'. {detail}")

        out = outputs[key]
        return (
            out.value.get_secret_value() if isinstance(out.value, Secret) else out.value
        )


def to_package_name(s: str) -> str:
    return inflection.underscore(s.strip().replace("-", "_"))


def to_posix(s: str | Path) -> str:
    return Path(s).as_posix()


PackageName = Annotated[
    str,
    BeforeValidator(to_package_name),
    StringConstraints(pattern=r"^[a-z_][a-z0-9_]*$"),
]
DistName = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")]
EntryPoint = Annotated[str, StringConstraints(pattern=r"^[\w.]+:[\w.]+$")]
MemberPath = Annotated[str, BeforeValidator(to_posix), StringConstraints(min_length=1)]

Workspace = dict[DistName, MemberPath]
Scripts = dict[DistName, EntryPoint]


class ProjectTable(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: DistName
    version: str | None = None
    scripts: Scripts = {}

    @property
    def package(self) -> str:
        return to_package_name(self.name)


PYPROJECT_TEMPLATE = """\
[project]
name = "{PROJECT_NAME}"
version = "0.1.0"
requires-python = ">=3.14"
dependencies = []

[build-system]
requires = ["uv_build>=0.11.18,<0.12"]
build-backend = "uv_build"
"""


class PyProject(BaseModel):
    cwd: Path
    template: str = PYPROJECT_TEMPLATE
    _doc: TOMLDocument | None = PrivateAttr(default=None)

    @property
    def path(self) -> Path:
        return self.cwd / "pyproject.toml"

    @property
    def exists(self) -> bool:
        return self.path.is_file()

    @property
    def doc(self) -> TOMLDocument:
        if self._doc is None:
            if not self.exists:
                raise FileNotFoundError(f"No pyproject.toml at {self.path}")
            self._doc = tomlkit.parse(self.path.read_text(encoding="utf-8"))
        return self._doc

    @property
    def project(self) -> ProjectTable:
        return ProjectTable.model_validate(self.doc.unwrap().get("project", {}))

    def reload(self) -> Self:
        self._doc = None
        return self

    def table(self, *keys: str) -> Table:
        t = self.doc
        for k in keys:
            t = t.setdefault(k, tomlkit.table())
        return cast(Table, t)

    @validate_call
    def create(self, name: PackageName) -> Self:
        self.path.write_text(self.template.format(PROJECT_NAME=name), encoding="utf-8")
        pkg = self.cwd / "src" / name
        pkg.mkdir(parents=True, exist_ok=True)
        (pkg / "__init__.py").touch(exist_ok=True)
        return self.reload()

    def ensure(self, name: str | None = None) -> Self:
        if self.exists:
            return self
        typer.secho(f"pyproject.toml not found at {self.path}", fg=typer.colors.YELLOW)
        return self.create(
            name or typer.prompt("What would you like to name your project?")
        )

    @validate_call
    def add_workspace(self, members: Workspace) -> Self:
        if not members:
            return self
        arr = self.table("tool", "uv", "workspace").setdefault(
            "members", tomlkit.array()
        )
        for m in members.values():
            if m not in arr:
                arr.append(m)
        sources = self.table("tool", "uv", "sources")
        for name in (n for n in members if n not in sources):
            it = tomlkit.inline_table()
            it["workspace"] = True
            sources[name] = it
        return self

    @validate_call
    def add_scripts(self, scripts: Scripts) -> Self:
        if not scripts:
            return self
        table = self.table("project", "scripts")
        for name, target in scripts.items():
            table[name] = target
        return self

    def save(self) -> Self:
        self.path.write_text(tomlkit.dumps(self.doc), encoding="utf-8")
        return self
