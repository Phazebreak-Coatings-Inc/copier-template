import time

from .typer_utils import sh

IMAGE = "postgres:18-alpine"


def image_exists() -> bool:
    return sh(f"docker image inspect {IMAGE}", check=False, silent=True) == 0


def pull_postgres(attempts: int = 3, backoff: float = 2.0) -> None:
    if image_exists():
        return
    last = None
    for i in range(attempts):
        try:
            sh(f"docker pull {IMAGE}", check=True, silent=True)
            return
        except Exception as e:
            last = e
            if image_exists():
                return
            if i < attempts - 1:
                time.sleep(backoff * (2**i))
    raise RuntimeError(f"Could not pull {IMAGE}: {last}")
