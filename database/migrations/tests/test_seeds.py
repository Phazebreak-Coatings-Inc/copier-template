import pytest
from database_util.utils import get_seeds
from sqlmodel import Session


@pytest.mark.parametrize("env", ["dev", "prod"])
def test_seeds_run(env, alembic_runner, alembic_engine):
    alembic_runner.migrate_up_to("head")
    for fn in get_seeds(env):
        with Session(alembic_engine) as s:
            fn(s)
            s.rollback()
