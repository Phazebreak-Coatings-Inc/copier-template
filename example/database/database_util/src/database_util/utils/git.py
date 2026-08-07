from contextlib import contextmanager
from pathlib import Path

import typer

from .typer_utils import sh

GIT_BOT_NAME = "github-actions[bot]"
GIT_BOT_EMAIL = "41898282+github-actions[bot]@users.noreply.github.com"


@contextmanager
def git_bot(message: str, path: Path = Path(".")):
    yield
    sh(f'git add -- "{path}"', check=True)
    if sh("git diff --cached --quiet", check=False).returncode == 0:
        typer.secho("[git-bot]: nothing to commit.", fg=typer.colors.YELLOW)
        return
    sh(
        f'git -c user.name="{GIT_BOT_NAME}" -c user.email="{GIT_BOT_EMAIL}" '
        f'commit -m "{message}"',
        check=True,
    )
    sh("git push", check=True)
