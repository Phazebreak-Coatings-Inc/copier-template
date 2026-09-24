import shutil
from pathlib import Path
from typing import Annotated

import copier
import tomlkit
import typer
from pydantic import BeforeValidator
from typer import Typer

from copier_template.util import PyProject, cli_exception_handler, quote, sh

from .config import (
    ANSWERS_FILE,
    COPIER_REPO,
    DEPENDENCIES,
    EXAMPLE_NAME,
    EXAMPLE_PROJECT_NAME,
    PACKAGES,
    SCRIPTS,
    WORKSPACE,
)


def validate_template_root(p: str | Path) -> Path:
    if isinstance(p, str):
        p = Path(p)
    if not (p / "copier.yml").exists():
        typer.secho("Run from the template repo root.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    return p


TemplateRoot = Annotated[Path, BeforeValidator(validate_template_root)]


def pyproject(cwd: Path) -> PyProject:
    return PyProject(cwd=cwd)  # template is already passed


def prepare_pyproject(cwd: Path, project_name: str | None = None) -> PyProject:
    return (
        pyproject(cwd)
        .ensure(project_name)
        .add_workspace(WORKSPACE)
        .add_dependencies(DEPENDENCIES)
        .add_dependencies(PACKAGES, group="dev")
        .add_scripts(SCRIPTS)
        .save()
    )


def require_clean(cwd: Path) -> None:
    r = sh("git status --porcelain", cwd=cwd, silent=True, check=False)
    if r.stdout.strip():
        typer.secho("Commit or stash changes before updating.", fg=typer.colors.YELLOW)
        raise typer.Exit(1)


CwdArgument = Annotated[
    Path, typer.Argument(help="Project directory.", resolve_path=True)
]

app = Typer()


@app.command(help="Hook up dependencies and workspaces correctly.")
@cli_exception_handler
def repair(cwd: CwdArgument = Path(".")):
    prepare_pyproject(cwd)


@app.command(help="Initialize a new project.")
@cli_exception_handler
def init(dest: CwdArgument = Path(".")):
    pyproject(dest).ensure()
    copier.run_copy(COPIER_REPO, str(dest), unsafe=True, answers_file=ANSWERS_FILE)
    repair(dest)


@app.command(help="Update your existing project.")
@cli_exception_handler
def update(cwd: CwdArgument = Path(".")):
    require_clean(cwd)
    sh(
        f"copier update -a {ANSWERS_FILE} --conflict inline --trust --skip-tasks",
        cwd=cwd,
    )
    repair(cwd)


@app.command(help="Destroy and regenerate the committed example project.", hidden=True)
@cli_exception_handler
def example():  # this command explicitly is not meant to update, it just doesn't work. it's already been tried.... sorry... :(
    root = validate_template_root(Path.cwd().resolve())
    dst = root / EXAMPLE_NAME

    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir()

    sh(
        f"uv run python -m copier copy {root} {dst} --trust --vcs-ref=HEAD -d project_name={EXAMPLE_PROJECT_NAME} --skip-tasks"
    )

    pp = pyproject(dst).ensure(EXAMPLE_PROJECT_NAME)
    source = tomlkit.inline_table()
    source.update({"path": "..", "editable": True})
    pp.table("tool", "uv", "sources")["copier-template"] = source
    pp.save()
    prepare_pyproject(dst, EXAMPLE_PROJECT_NAME)
    sh("uv build --all-packages", cwd=dst)
    sh('uv run pytest tests/test_example.py -m "not slow"', cwd=root)
    sh("uv run pytest --ignore=example", cwd=dst, check=False)
    typer.secho(f"Regenerated {dst}", fg=typer.colors.GREEN)
