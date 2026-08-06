import subprocess
from pathlib import Path
from typing import Annotated

import copier
import tomlkit
import typer
from typer import Typer

type PyProject = tomlkit.TOMLDocument

type WorkspaceMembers = list[str]

COPIER_REPO = "gh:Phazebreak-Coatings-Inc/alembic-environment"

ANSWERS_FILE = ".alembic-environment-answers.yml"

WORKSPACE = {
    "database_core": "database/database_core",
    "database_util": "database/database_util",
    "models": "database/models",
    "migrations": "database/migrations",
    "environments": "database/environments",
}

PACKAGES = [
    "alembic>=1.18.4",
    "copier>=9.15.1",
    "sqlalchemy>=2.0.50",
    "sqlmodel>=0.0.38",
    "typer>=0.26.6",
    "pytest-alembic>=0.12.1",
    "pytest>=9.0.3",
    "pydantic-settings>=2.14.1",
    "psycopg[binary]>=3.3.4",
    "ruff>=0.15.15",
    "tomlkit>=0.15.0",
    "sqlacodegen>=4.0.3",
    "inflection>=0.5.1",
]


def sh(cmd: str, check=True, **kwargs):
    try:
        subprocess.run(cmd, shell=True, check=check, **kwargs)
    except subprocess.CalledProcessError as e:
        typer.secho(f"failed: {cmd}", fg=typer.colors.RED, err=True)
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
    for m in ext + [m for m in workspace.values() if m not in ext]:  # paths
        arr.append(m)
    ws["members"] = arr

    sources = sd(uv, "sources")
    for name in workspace:  # names
        if name not in sources:
            it = tomlkit.inline_table()
            it["workspace"] = True
            sources[name] = it
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


@app.command(help="Update an existing alembic-environment project.")
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
    write_pyproject(p, add_workspaces(get_pyproject(p), WORKSPACE))
    sh(f"uv add --workspace {' '.join(WORKSPACE)}", cwd=p)
    sh(
        f"uv add --dev {' '.join(PACKAGES)}", cwd=p
    ) 
    sh("uv sync", cwd=p)
