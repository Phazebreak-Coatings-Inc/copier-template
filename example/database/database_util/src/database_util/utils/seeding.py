import importlib
import pkgutil
from collections import defaultdict
from typing import Annotated, Callable, Literal, get_type_hints

import inflection
import typer
from pydantic import BeforeValidator, validate_call
from sqlmodel import Session

from .environments import DatabaseEnvironment, get_database_setting
from .paths import DIR_SEEDS
from .typer_utils import run_steps

SEEDABLE_ENVS = ["dev", "prod"]


def is_valid_seedable_env(env: str) -> "SeedableDatabaseEnvironment":
    if env not in SEEDABLE_ENVS:
        raise ValueError(
            f"'{env}' is not a valid database environment, choose one of {SEEDABLE_ENVS}"
        )
    return env  # type: ignore


SeedFunction = Callable[[Session], None]
SeedRegistry = dict[DatabaseEnvironment, list[SeedFunction]]
RequiresRegistry = dict[SeedFunction, list[SeedFunction]]
SeedableDatabaseEnvironment = Annotated[
    Literal["dev", "prod"], BeforeValidator(is_valid_seedable_env)
]
SeedableEnvArg = Annotated[
    SeedableDatabaseEnvironment,
    typer.Argument(
        help="Choose which environment to seed for, either 'dev' or 'prod' because staging is a separate flow."
    ),
]


class SeedingException(Exception): ...


SEEDS: SeedRegistry = defaultdict(list)
REQUIRES: RequiresRegistry = {}
SEED_TEMPLATE = """from models import *
from sqlmodel import Session
from database_core import seed

@seed(['{env}'])
def {name}(session: Session) -> None:
    ...
"""


@validate_call
def generate_seed_file(
    env: SeedableDatabaseEnvironment, name: str, dry_run: bool = False
):
    n = inflection.underscore(name)
    p = DIR_SEEDS / f"{n}.py"
    if p.exists():
        typer.confirm(
            f"{p.name} already exists, are you sure you want to overwrite it?",
            abort=True,
        )
    else:
        p.touch()

    t = SEED_TEMPLATE.format(env=env, name=n)

    if dry_run:
        typer.secho(
            f"Would write new seed file to {p}: \n\n{t}\n", fg=typer.colors.YELLOW
        )

    p.write_text(t)
    typer.secho(f"Wrote new seed file to {p}: \n\n{t}\n", fg=typer.colors.GREEN)
    return


@validate_call
def seed(
    envs: list[SeedableDatabaseEnvironment], requires: list[SeedFunction] | None = None
):
    def dec(fn) -> SeedFunction:
        if not (sesh := get_type_hints(fn).get("session", None)):
            raise SeedingException(
                f"session must be passed as a type hint in fn {fn.__name__}"
            )
        if not (isinstance(sesh, type) and issubclass(sesh, Session)):
            raise SeedingException(
                f"`session` of {fn.__name__} must be a sqlmodel.Session subclass"
            )
        REQUIRES[fn] = requires or []
        for env in envs:
            SEEDS[env].append(fn)
        return fn

    return dec


@validate_call
def count_seeds(env: SeedableDatabaseEnvironment) -> int:
    return len(SEEDS[env])


@validate_call
def get_seeds(env: SeedableDatabaseEnvironment) -> list[SeedFunction]:
    return SEEDS[env]


@validate_call
def sort_seeds(env: SeedableDatabaseEnvironment) -> list[SeedFunction]:
    fns = get_seeds(env)
    registered, out, done, stack = set(fns), [], set(), set()

    def visit(fn):
        if fn in done:
            return
        if fn in stack:
            raise SeedingException(f"circular seed dependency at '{fn.__name__}'")
        if fn not in registered:
            raise SeedingException(
                f"'{fn.__name__}' is required but not registered for environment '{env}'"
            )
        stack.add(fn)
        for dep in REQUIRES.get(fn, []):
            visit(dep)
        stack.discard(fn)
        done.add(fn)
        out.append(fn)

    for fn in fns:
        visit(fn)

    return out


def load_seeds() -> None:
    import migrations.seeds as pkg

    for m in pkgutil.iter_modules(pkg.__path__):
        importlib.import_module(f"{pkg.__name__}.{m.name}")


@validate_call
def execute_seeds(
    env: SeedableDatabaseEnvironment, dry_run: bool = False, interactive: bool = True
):
    load_seeds()
    errors: list[tuple[str, Exception]] = []
    with Session(get_database_setting(env).engine) as s:

        def make_step(fn):
            def step():
                try:
                    with s.begin_nested():
                        fn(s)
                except Exception as e:
                    errors.append((fn.__name__, e))

            return step

        fns = [make_step(fn) for fn in sort_seeds(env)]

        if len(fns) == 0:
            typer.secho(
                f"Found 0 seeds for environment '{env}'...", fg=typer.colors.YELLOW
            )
            return

        if interactive and not dry_run:
            typer.confirm(
                f"This action will run {count_seeds(env)} functions on environment '{env},' Are you sure you want to proceed?",
                abort=True,
            )

        run_steps(label=f"Seeding '{env}' environment", fns=fns)

        if errors:
            s.rollback()
            details = "\n".join(f"  {name}: {e}" for name, e in errors)
            raise SeedingException(f"{len(errors)} seed(s) failed:\n{details}")
        if dry_run:
            s.rollback()
            typer.secho(
                f"Successfully ran and rolled-back {len(fns)} seeding functions in '{env}' environment.",
                fg=typer.colors.GREEN,
            )
            return

        typer.secho(
            f"Successfully ran {len(fns)} seeding functions in '{env}' environment.",
            fg=typer.colors.GREEN,
        )
        s.commit()
