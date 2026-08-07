import importlib
from collections import defaultdict
from pathlib import Path
from typing import Callable, get_type_hints

import typer
from alembic import op
from pydantic import validate_call
from sqlmodel import Session

from .paths import DIR_BACKFILLS
from .typer_utils import Revision

BackfillFunction = Callable[[Session], None]
BackfillRegistry = dict[str, list[BackfillFunction]]

BACKFILLS: BackfillRegistry = defaultdict(list)

BACKFILL_TEMPLATE = """
from sqlmodel import Session
from database_core import backfill


@backfill("{rev}")
def backfill_{rev}(session: Session) -> None:
    ...
"""


class BackfillException(Exception): ...


@validate_call
def backfill(rev: Revision):
    def dec(fn) -> BackfillFunction:
        if not (sesh := get_type_hints(fn).get("session", None)):
            raise BackfillException(
                f"session must be passed as a type hint in fn {fn.__name__}"
            )
        if not (isinstance(sesh, type) and issubclass(sesh, Session)):
            raise BackfillException(
                f"`session` of {fn.__name__} must be a sqlmodel.Session subclass"
            )
        BACKFILLS[rev].append(fn)
        return fn

    return dec


def get_backfills(rev: str) -> list[BackfillFunction]:
    name = f"migrations.backfills.{rev}"
    try:
        importlib.import_module(name)
    except ModuleNotFoundError as exc:
        if exc.name != name:
            raise
        return []
    return BACKFILLS[rev]


def run_backfill(rev: str) -> None:
    """Called from a revision's upgrade(). No-op when the revision has no backfill."""
    if not (fns := get_backfills(rev)):
        return
    with Session(bind=op.get_bind()) as session:
        for fn in fns:
            fn(session)
        session.flush()


def write_backfill_stub(rev: str) -> Path:
    DIR_BACKFILLS.mkdir(parents=True, exist_ok=True)
    (DIR_BACKFILLS / "__init__.py").touch()
    p = DIR_BACKFILLS / f"{rev}.py"
    if not p.exists():
        p.write_text(BACKFILL_TEMPLATE.format(rev=rev))
        typer.secho(f"Wrote backfill stub {p}", fg=typer.colors.GREEN)
    else:
        typer.secho(
            f"Backfill already exists for this revision at {p}", fg=typer.colors.YELLOW
        )
    return p
