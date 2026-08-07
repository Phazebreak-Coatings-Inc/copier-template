import subprocess


def ruff_format(code: str) -> str:
    p = subprocess.run(
        "uvx ruff format -", shell=True, input=code, capture_output=True, text=True
    )
    return p.stdout if p.returncode == 0 else code
