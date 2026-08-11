import subprocess
from pathlib import Path
from typing import Annotated

import copier
import tomlkit
import typer
from typer import Typer

type PyProject = tomlkit.TOMLDocument

type WorkspaceMembers = list[str]

import shutil
import tempfile

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


def get_pyproject(cwd: Path) -> tomlkit.TOMLDocument:
    p = cwd / "pyproject.toml"
    s = f"'pyproject'.toml not found at {p}"

    if not p.exists():
        if typer.confirm(f"{s}: Initialize a new uv project?", abort=True):
            sh("uv init")
            if not p.exists():
                raise FileNotFoundError(s)
    return tomlkit.parse(p.read_text())


def add_workspaces(p: PyProject, workspace: dict[str, str]) -> PyProject:
    def sd(t, name):
        return t.setdefault(name, tomlkit.table())

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

    table = sd(sd(p, "project"), "scripts")
    for name, target in scripts.items():
        table[name] = target
    return p


def write_pyproject(cwd: Path, p: PyProject) -> None:
    (cwd / "pyproject.toml").write_text(tomlkit.dumps(p))


app = Typer(pretty_exceptions_show_locals=False)


@app.command(help="Initialize a new alembic-environment project.")
def init(
    dest: Annotated[
        str, typer.Argument(help="Directory to initialize project in.")
    ] = ".",
):
    get_pyproject(Path(dest).resolve())
    copier.run_copy(COPIER_REPO, dest)
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
    for name, member in WORKSPACE.items():
        if not (p / member / "pyproject.toml").exists():
            typer.secho(
                f"member {member!r} ({name}) has no pyproject.toml",
                fg=typer.colors.RED,
                err=True,
            )
            raise typer.Exit(1)
    write_pyproject(p, add_scripts(add_workspaces(get_pyproject(p), WORKSPACE), SCRIPTS))
    sh(f"uv add --workspace {' '.join(WORKSPACE)}", cwd=p)
    sh(f"uv add --dev {' '.join(PACKAGES)}", cwd=p)
    sh("uv sync", cwd=p)


EXAMPLE_PYPROJECT = f"""\
[project]
name = "{EXAMPLE_PROJECT_NAME}"
version = "0.1.0"
requires-python = ">=3.14"
dependencies = []

[build-system]
requires = ["uv_build>=0.11.18,<0.12"]
build-backend = "uv_build"
"""


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
    (dst / "pyproject.toml").write_text(EXAMPLE_PYPROJECT)
    pkg = dst / "src" / EXAMPLE_PROJECT_NAME.replace("-", "_")
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").touch()

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "template"
        shutil.copytree(root, src, ignore=shutil.ignore_patterns(".git", ".venv"))
        copier.run_copy(str(src), str(dst), defaults=True, unsafe=True, quiet=False)

    (dst / ANSWERS_FILE).unlink(missing_ok=True)
    repair(str(dst))
    sh("uv build --all-packages", cwd=dst)
    sh('uv run pytest tests/test_example.py -m "not slow"', cwd=root)
    sh("uv run pytest", cwd=dst)
    typer.secho(f"Regenerated {dst}", fg=typer.colors.GREEN)
