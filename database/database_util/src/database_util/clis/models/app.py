import typer
from typer import Typer
from ...utils import (
    PKG_MODELS,
    INIT_MODELS,
    TABLES_SQL,
    SQLGenerator,
    SQLReverseGenerator,
    repair_model_init,
    DryRun,
    e,
)
from ..migrations.app import migrate

app = Typer(pretty_exceptions_show_locals=False)

@app.command(help=f"Create models from {TABLES_SQL}")
@e
def g(
    dry_run: DryRun = False,
):
    typer.secho(f"Attempting to generate models from {TABLES_SQL.name}", fg=typer.colors.YELLOW)
    s = SQLGenerator()
    typer.secho(f"\nRendered {s.len_models} model(s) from {TABLES_SQL.name}", fg=typer.colors.GREEN)
    if not dry_run:
        s.write_files()
        repair()
        migrate()
        typer.secho("Wrote files successfully.", fg=typer.colors.GREEN)


@app.command(help=f"Merge ORM-only columns back into {TABLES_SQL} as comments.")
@e
def rg(dry_run: DryRun = False):
    import models  # noqa: F401
    from sqlmodel import SQLModel

    typer.secho(
        f"Attempting to reverse generate mixin fields back to {TABLES_SQL.name}",
        fg=typer.colors.YELLOW
    )
    r = SQLReverseGenerator(SQLModel.metadata)
    if not dry_run:
        r.write(dry_run=dry_run)
        migrate()
        typer.secho("Wrote files successfully", fg=typer.colors.GREEN)

@app.command(help="Auto hook up imports.")
@e
def repair(dry_run: DryRun = False):
    typer.secho(f"Attempting to repair {INIT_MODELS} file", fg=typer.colors.YELLOW)
    repair_model_init(dry_run=dry_run)
    if not dry_run:
        typer.secho("Successfully wrote new imports.", fg=typer.colors.GREEN)


@app.command(help="CICD pipeline for generating and reverse generating models.")
def cicd():
    from ...utils import git_bot

    with git_bot("chore: regenerate models from tables.sql", PKG_MODELS):
        g()
    with git_bot("chore: reverse-generate tables.sql", TABLES_SQL):
        rg()
