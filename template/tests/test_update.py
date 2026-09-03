import pytest
import subprocess
from copier_template.main import sh, EXAMPLE_PROJECT_NAME
from pathlib import Path

TEMPLATE_ROOT = Path(__file__).resolve().parents[1]

@pytest.mark.slow
def test_update(tmp_path):
    dst = tmp_path / "proj"
    prev = subprocess.check_output(
        ["git", "describe", "--tags", "--abbrev=0", "HEAD~1"],
        cwd=TEMPLATE_ROOT,
        text=True,
    ).strip()
    print(f'prev version is {prev}')

    sh(
        f"copier copy {TEMPLATE_ROOT} {dst} --trust --vcs-ref={prev} "
        f"-d project_name={EXAMPLE_PROJECT_NAME} -d github_repo=test/test "
        f"-d your_name=Test --defaults"
    )
    sh("git init", cwd=dst)
    sh("git add -A", cwd=dst)
    sh('git -c user.email=t@t -c user.name=t commit -m "init"', cwd=dst)
    sh("copier update --trust --vcs-ref=HEAD --defaults --conflict rej", cwd=dst)

    assert not list(dst.rglob("*.rej"))
