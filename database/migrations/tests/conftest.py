import pytest
from pytest_alembic.config import Config

from database_util.utils import migration_settings


@pytest.fixture
def alembic_engine():
    return migration_settings.engine


@pytest.fixture
def alembic_config():
    """Override this fixture to configure the exact alembic context setup required."""
    return Config()
