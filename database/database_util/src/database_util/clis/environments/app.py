import typer
from pathlib import Path
import traceback
from typing import Annotated
from sqlmodel import Session, text
from ...utils import EnvArg, get_database_setting, e, ProdDatabaseSettings, StagingDatabaseSettings, DryRun

app = typer.Typer()


@app.command(help="Starts the database cluster for a specific environment.")
@e
def up(
    env: EnvArg,
    startup: Annotated[bool, typer.Option("-s", "--startup", help="If enabled, runs startup steps no matter what. If false, only runs if the database is currently down.")] = False,
    reapply: Annotated[bool, typer.Option("-r", "--reapply", help="If enabled, will replan and reapply if already provisioned.")] = False
):

    s = get_database_setting(env) #type: ignore
    if reapply:
        if env == "dev":
            raise ValueError("Can't reapply against a non-terraformed database.")
        s: ProdDatabaseSettings | StagingDatabaseSettings
        s.apply()
    s.up(startup)



@app.command(help="Turns off the database cluster for a specific environment.")
@e
def down(
    env: EnvArg, 
    destroy: Annotated[bool, typer.Option("--destroy", "-d")] = False
):
    s = get_database_setting(env)
    s.down() if not destroy else s.destroy()


@app.command(help="Tests a database environment.")
@e
def test(
    env: EnvArg,
):
    s = get_database_setting(env)
    s.test()


@app.command(help="Ping a database environment.")
@e
def ping(
    env: EnvArg
):
    s = get_database_setting(env)
    s.ping(verbose=True)


@app.command(name="exec", help="Execute SQL from the command line or a file.")
@e
def exec(
    env: EnvArg,
    sql: Annotated[
        str, typer.Option("--sql", "-s", help="The statement to execute.")
    ] = "SELECT 1",
    file: Annotated[
        Path | None, typer.Option("--file", "-f", help="File to execute.")
    ] = None,
    dry_run: DryRun = False,
):
    s = get_database_setting(env)
    statement = file.read_text() if file else sql

    if not dry_run and env != "dev":
        typer.confirm(f"Run against '{env}'?\n\n{statement}\n", abort=True)

    s.ping()

    with Session(s.engine) as ses:
        try:
            result = ses.exec(text(statement)) #type: ignore
            if result.returns_rows:
                rows = result.fetchall()
                for r in rows:
                    typer.echo(dict(r._mapping))
                typer.secho(f"{len(rows)} row(s)", fg=typer.colors.CYAN)
            else:
                if result.rowcount >= 0:
                    typer.secho(f"{result.rowcount} row(s) affected", fg=typer.colors.CYAN)
                else:
                    typer.secho("OK", fg=typer.colors.CYAN)
        except Exception:
            ses.rollback()
            typer.secho(traceback.format_exc(), fg=typer.colors.RED, err=True)
            raise typer.Exit(1)

        if dry_run:
            ses.rollback()
            typer.secho("Dry run - rolled back.", fg=typer.colors.YELLOW)
        else:
            ses.commit()
