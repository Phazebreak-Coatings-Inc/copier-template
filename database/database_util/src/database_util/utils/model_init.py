import ast
import typer
from .paths import PKG_MODELS, INIT_MODELS
from .misc import ruff_format
from pathlib import Path


def model_exports(init: Path) -> list[str]:
    for n in ast.parse(init.read_text()).body:
        if isinstance(n, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "__all__" for t in n.targets
        ):
            if isinstance(n.value, ast.List):
                return [e.value for e in n.value.elts if isinstance(e, ast.Constant)]  # type: ignore
    return []


def repair_model_init(dry_run: bool = False):
    lines: list[str] = [
        "from .base_model import SQLModelBase"
    ]
    all_names: list[str] = ["SQLModelBase"]
    for d in sorted(p for p in PKG_MODELS.iterdir() if (p / "__init__.py").exists()):
        names = model_exports(d / "__init__.py")
        if not names:
            continue
        lines.append(f"from .{d.name} import " + ", ".join(names))
        all_names += names


    body = "\n".join(lines)
    rebuilds = [n for n in all_names if not n.endswith("Base")]
    if rebuilds:
        body += "\n\n" + "\n".join(f"{n}.model_rebuild()" for n in rebuilds)
    body += "\n\n__all__ = [" + ", ".join(f'"{n}"' for n in all_names) + "]\n"
    if not dry_run:
        INIT_MODELS.write_text(ruff_format(body))
    if dry_run:
        typer.secho(f"Would have generated: \n\n {body}", fg=typer.colors.YELLOW)
