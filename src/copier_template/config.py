COPIER_REPO = "gh:Phazebreak-Coatings-Inc/alembic-environment"
ANSWERS_FILE = ".alembic-environment-answers.yml"
EXAMPLE_NAME = "example"
EXAMPLE_PROJECT_NAME = "example-project"

WORKSPACE = {
    "database_core": "database/database_core",
    "database_util": "database/database_util",
    "models": "database/models",
    "migrations": "database/migrations",
    "environments": "database/environments",
}

SCRIPTS = {
    "models": "database_util.clis.models.app:app",
    "migrations": "database_util.clis.migrations.app:app",
    "environments": "database_util.clis.environments.app:app",
}

PACKAGES = [
    "skylos>=4.29.0",
    "debugpy>=1.8.21",
    "alembic>=1.18.4",
    "sqlalchemy>=2.0.50",
    "sqlmodel>=0.0.38",
    "pytest-alembic>=0.12.1",
    "pytest>=9.0.3",
    "pydantic-settings>=2.14.1",
    "psycopg[binary]>=3.3.4",
    "ruff>=0.15.15",
    "tomlkit>=0.15.0",
    "sqlacodegen>=4.0.3",
    "inflection>=0.5.1",
    "copier>=9.15.1",
    "typer>=0.26.6",
    "sqlglot>=30.12.0",
]

EXAMPLE_PRESENT = ["alembic.ini", "database/models/tables.sql"]
