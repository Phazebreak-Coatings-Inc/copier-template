import subprocess
from pathlib import Path

import pytest
import tomlkit
import yaml

from copier_template.config import (
    EXAMPLE_NAME,
    EXAMPLE_PRESENT,
    EXAMPLE_PROJECT_NAME,
    SCRIPTS,
    WORKSPACE,
)

TEMPLATE_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = TEMPLATE_ROOT / EXAMPLE_NAME


@pytest.mark.parametrize("name,path", WORKSPACE.items())
def test_member_is_a_package(name, path):
    assert (EXAMPLE / path / "src" / name / "__init__.py").exists()


@pytest.fixture(scope="session")
def doc():
    return tomlkit.parse((EXAMPLE / "pyproject.toml").read_text())


GENERATED_AFTER_COPY = {"pyproject.toml", "uv.lock", "dist", ".venv", "src"}


def _root_exclusions() -> list[str]:
    cfg = yaml.safe_load((TEMPLATE_ROOT / "copier.yml").read_text())
    return [
        p
        for e in cfg["_exclude"]
        if e.startswith("/")
        for p in [e.strip("/")]
        if p not in GENERATED_AFTER_COPY
    ]


def test_user_project_preserved(doc):
    assert doc["project"]["name"] == EXAMPLE_PROJECT_NAME


@pytest.mark.parametrize("name,path", WORKSPACE.items())
def test_member_landed_and_pinned(doc, name, path):
    assert (EXAMPLE / path / "pyproject.toml").exists()
    assert path in list(doc["tool"]["uv"]["workspace"]["members"])
    key = name.replace("_", "-")
    assert doc["tool"]["uv"]["sources"][key]["workspace"] is True


@pytest.mark.parametrize("name,target", SCRIPTS.items())
def test_script_registered(doc, name, target):
    assert doc["project"]["scripts"][name] == target


@pytest.mark.parametrize("path", EXAMPLE_PRESENT)
def test_present(path):
    assert (EXAMPLE / path).exists()


@pytest.mark.parametrize("path", _root_exclusions())
def test_excluded_path_absent(path):
    assert not (EXAMPLE / path).exists(), f"{path} is in _exclude but landed anyway"


@pytest.mark.slow
@pytest.mark.parametrize("name", SCRIPTS)
def test_script_runs(name):
    subprocess.run(["uv", "sync"], cwd=EXAMPLE, check=True)
    r = subprocess.run(
        ["uv", "run", name, "--help"], cwd=EXAMPLE, capture_output=True, text=True
    )
    assert r.returncode == 0, r.stderr
