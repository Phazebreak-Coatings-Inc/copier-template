# database/migrations/tests/conftest.py
import pytest
from database_util.utils import migration_settings
from pytest_alembic.config import Config


@pytest.fixture(scope="session", autouse=True)
def migrations_database():
    try:
        migration_settings.ping()
        yield
        return
    except Exception:
        pass
    with migration_settings.temp():
        yield


@pytest.fixture
def alembic_engine():
    return migration_settings.engine


@pytest.fixture
def alembic_config():
    """Override this fixture to configure the exact alembic context setup required."""
    return Config()
