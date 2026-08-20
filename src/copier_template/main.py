import subprocess
import inflection
from pathlib import Path
from typing import Annotated

import copier
import tomlkit
import typer
from typer import Typer

type PyProject = tomlkit.TOMLDocument

type WorkspaceMembers = list[str]

import shutil

from .config import (
    ANSWERS_FILE,
    COPIER_REPO,
    EXAMPLE_NAME,
    EXAMPLE_PROJECT_NAME,
    PACKAGES,
    SCRIPTS,
    WORKSPACE,
)


def sh(cmd: str, silent=False, check=True, **kwargs) -> subprocess.CompletedProcess:
    if silent:
        kwargs.setdefault("stdout", subprocess.PIPE)
        kwargs.setdefault("stderr", subprocess.PIPE)
        kwargs.setdefault("text", True)
    try:
        return subprocess.run(cmd, shell=True, check=check, **kwargs)
    except subprocess.CalledProcessError as e:
        if not silent:
            typer.secho(f"\nFailed: {cmd}", fg=typer.colors.BRIGHT_RED, err=True)
            if output := (e.stderr or e.stdout):
                typer.secho(output.rstrip(), fg=typer.colors.RED, err=True)
        raise typer.Exit(e.returncode) from None


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


def get_pyproject(cwd: Path, fallback_name: str | None = None) -> tomlkit.TOMLDocument:
    p = cwd / "pyproject.toml"
    if not p.exists():
        print(f"'pyproject'.toml not found at {p}")
        p.touch(exist_ok=True)
        n = fallback_name or inflection.underscore(
            typer.prompt("What would you like to name your pyproject?")
        )
        p.write_text(PYPROJECT_TEMPLATE.format(PROJECT_NAME=n))
        b = cwd / "src" / n
        b.mkdir(parents=True, exist_ok=True)
        (b / "__init__.py").touch(exist_ok=True)

    return tomlkit.parse(p.read_text())


def add_workspaces(p: PyProject, workspace: dict[str, str]) -> PyProject:
    def sd(t, name):
        return t.setdefault(name, tomlkit.table())

    if len(workspace) == 0:
        return p

    uv = sd(sd(p, "tool"), "uv")
    ws = sd(uv, "workspace")
    ext = list(ws.get("members", []))

    arr = tomlkit.array()
    for m in ext + [m for m in workspace.values() if m not in ext]:
        arr.append(m)
    ws["members"] = arr

    sources = sd(uv, "sources")
    for name in workspace:
        if name not in sources:
            it = tomlkit.inline_table()
            it["workspace"] = True
            sources[name] = it
    return p


def add_scripts(p: PyProject, scripts: dict[str, str]) -> PyProject:
    def sd(t, name):
        return t.setdefault(name, tomlkit.table())

    if len(scripts) == 0:
        return p

    table = sd(sd(p, "project"), "scripts")
    for name, target in scripts.items():
        table[name] = target
    return p


def write_pyproject(cwd: Path, p: PyProject) -> None:
    (cwd / "pyproject.toml").write_text(tomlkit.dumps(p))


def prepare_pyproject(p: Path, project_name: str | None = None):
    write_pyproject(
        p,
        add_scripts(add_workspaces(get_pyproject(p, project_name), WORKSPACE), SCRIPTS),
    )
    if len(WORKSPACE) > 0:
        sh(f"uv add --workspace {' '.join(WORKSPACE)}", cwd=p)
    if len(PACKAGES) > 0:
        sh(f"uv add --dev {' '.join(PACKAGES)}", cwd=p)
    sh("uv sync", cwd=p)


app = Typer(pretty_exceptions_show_locals=False)


@app.command(help="Initialize a new copier-template project.")
def init(
    dest: Annotated[
        str, typer.Argument(help="Directory to initialize project in.")
    ] = ".",
):
    get_pyproject(Path(dest).resolve())
    copier.run_copy(COPIER_REPO, dest, unsafe=True)
    repair(dest)


@app.command(help="Update your existing project.")
def update(
    abort: Annotated[
        bool,
        typer.Option(
            "--abort",
            "-a",
            help="If the abort flag is triggered, this will reset the attempt to update the copier project. Prudent when the changes are too much to resolve.",
        ),
    ] = False,
):
    match abort:
        case False:
            typer.confirm(
                "Are you sure you want to update? If you need to abort mid-update, it will trigger a 'git reset.' Make sure to save all uncommitted changes.",
                abort=True,
            )
            sh(f"copier update -a {ANSWERS_FILE} --conflict inline")
        case True:
            typer.confirm(
                "Are you sure you want to abort? This will trigger a 'git reset.'",
                abort=True,
            )
            sh("git reset")
            sh("git checkout .")
            sh("git clean -d -i")
    repair()


@app.command(help="Hook up dependencies and workspaces correctly.")
def repair(
    cwd: Annotated[
        str, typer.Argument(help="Directory to initialize project in.")
    ] = ".",
):
    p = Path(cwd).resolve()
    prepare_pyproject(p)


@app.command(help="Destroy and regenerate the committed example project.")
def example():
    root = Path.cwd().resolve()
    if not (root / "copier.yml").exists():
        typer.secho("Run from the template repo root.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    dst = root / EXAMPLE_NAME
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir()

    sh(
        f"uv run python -m copier copy {str(root)} {str(dst)} --trust -d project_name={EXAMPLE_PROJECT_NAME} --skip-tasks"
    )

    (dst / ANSWERS_FILE).unlink(missing_ok=True)
    prepare_pyproject(dst, EXAMPLE_PROJECT_NAME)
    sh("uv build --all-packages", cwd=dst)
    sh('uv run pytest tests/test_example.py -m "not slow"', cwd=root)
    sh("uv run pytest --ignore=example", cwd=dst, check=False)
    typer.secho(f"Regenerated {dst}", fg=typer.colors.GREEN)

