COPIER_REPO = "gh:Phazebreak-Coatings-Inc/copier-template"
"""The repo that copier should target."""

ANSWERS_FILE = ".copier-template-answers.yml"
"""The actual answers file that will be saved after user-interaction. 

If it has the same name as another copier-template project, your template will break.
"""

EXAMPLE_NAME = "example"
"""This is only used for the target dir where 'uv run python -m copier_template example ends up."""

EXAMPLE_PROJECT_NAME = "example-project"
"""This is what the pyproject.toml.[project].name will be after running 'uv run python -m copier_template example'"""

WORKSPACE: dict[str, str] = {}
"""Workspace members to add to the target pyproject.

Maps package name to its path.

```python
{"some_dependency": "./some_dependency"}
```
"""

SCRIPTS: dict[str, str] = {}
"""Will add these scripts to the target pyproject, i.e.

```python
    {"my_script": "some_dependency.__main__:my_script"}
```
"""

PACKAGES = [
    "copier>=9.15.1",
    "inflection>=0.5.1",
    "pytest>=9.1.1",
    "tomlkit>=0.15.0",
    "typer>=0.26.6",
]
"""The packages that should be added to the target pyproject."""

