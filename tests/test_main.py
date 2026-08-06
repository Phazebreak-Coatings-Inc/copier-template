import tomlkit

from alembic_environment.main import add_workspaces


def test_add_workspaces_fresh():
    doc = tomlkit.parse("")
    out = add_workspaces(
        doc, {"models": "database/models", "migrations": "database/migrations"}
    )
    assert list(out["tool"]["uv"]["workspace"]["members"]) == [
        "database/models",
        "database/migrations",
    ]
    assert out["tool"]["uv"]["sources"]["models"]["workspace"] is True


def test_add_workspaces_merges_existing():
    doc = tomlkit.parse('[tool.uv.workspace]\nmembers = ["database/models"]\n')
    out = add_workspaces(
        doc, {"models": "database/models", "migrations": "database/migrations"}
    )
    assert list(out["tool"]["uv"]["workspace"]["members"]) == [
        "database/models",
        "database/migrations",
    ]
