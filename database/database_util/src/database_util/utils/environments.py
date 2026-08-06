from contextlib import contextmanager
import typer
import json
import time
import subprocess
from typing import (
    Annotated,
    Literal,
    cast,
    ClassVar,
    Mapping,
    TypedDict,
    Any,
    Callable,
)
from abc import abstractmethod, ABC
from pathlib import Path
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.util.exc import CommandError
from pydantic import (
    BeforeValidator,
    validate_call,
    BaseModel,
    SecretStr,
    model_validator,
    PrivateAttr
)
from functools import cached_property
from pydantic_settings import BaseSettings
from sqlalchemy import create_engine, text, URL
from .paths import (
    ENV_DEV_COMPOSE,
    PKG_PROD,
)

ENVS = ["dev", "staging", "prod", "mig"]


def is_valid_database_env(env: str) -> "DatabaseEnvironment":
    if env not in ENVS:
        raise ValueError(
            f"'{env}' is not a valid database environment, choose one of {ENVS}"
        )
    return env  # type: ignore


DatabaseEnvironment = Annotated[
    Literal["dev", "staging", "prod", "mig"], BeforeValidator(is_valid_database_env)
]


class BaseDatabaseSettings(ABC, BaseSettings):
    database_host: str | None = "localhost"
    database_port: int | None = 5432
    database_username: str | None = None
    database_password: str | None = None
    database_name: str | None = None

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.database_username}:{self.database_password}"
            f"@{self.database_host}:{self.database_port}/{self.database_name}"
        )

    @property
    def engine(self):
        return create_engine(self.database_url, connect_args={"connect_timeout": 3})

    @abstractmethod
    def get_environment_str(self) -> str: ...

    def ping(self, attempts: int = 1, delay: float = 0.5, verbose: bool = False) -> None:
        engine = self.engine
        started = time.perf_counter()
        last: Exception | None = None
        try:
            for i in range(attempts):
                try:
                    with engine.connect() as conn:
                        conn.execute(text("SELECT 1"))
                    if verbose:
                        typer.secho(
                            f"{self.database_name} ready in "
                            f"{(time.perf_counter() - started) * 1000:.0f}ms", fg=typer.colors.GREEN
                        )
                    return
                except Exception as e:
                    last = e
                    if i + 1 >= attempts:
                        break
                    if verbose:
                        typer.secho(
                            f"Waiting for {self.database_name} ({i + 1}/{attempts})..."
                        )
                    time.sleep(delay)
        finally:
            engine.dispose()

        raise RuntimeError(
            f"Database connection to {self.database_name} failed after "
            f"{attempts} attempt(s): {last}"
        ) from last

    def up(self, startup: bool = False) -> None:
        from .typer_utils import run_steps

        try:
            self.ping()
            typer.secho(f"Database '{self.get_environment_str()}' is already up.", fg=typer.colors.GREEN)
        except Exception:
            self.start()
            self.ping(attempts=60, verbose=True)
            startup = True
           
        if startup:
            run_steps(fns=self.up_steps(), label="Running startup steps...")


    @abstractmethod
    def start(self) -> None: ...

    def up_steps(self) -> list[Callable]:
        return [
            self.upgrade,
            self.seed,
        ]

    @abstractmethod
    def down(self) -> None: ...

    @abstractmethod
    def destroy(self) -> None: ...

    @abstractmethod
    def test(self) -> bool: ...

    def upgrade(self):
        from database_util.clis.migrations.app import apply
        apply(self.get_environment_str(), interactive=False) #type: ignore

    def seed(self):
        from database_util.clis.migrations.app import seed
        if (env := self.get_environment_str()) in ["dev", "prod"]:
            return seed(env) #type: ignore
        if env == "staging":
            return self.stage()

    def stage(self): ...

    @contextmanager
    def temp(self):
        try:
            self.up()
            yield None
        finally:
            self.down()

class TerraformOutputError(Exception): ...

class TerraformOutput(BaseModel):
    value: str | int | SecretStr
    sensitive: bool
    type: str

    @model_validator(mode="after")
    def wrap_sensitive(self):
        if self.sensitive and not isinstance(self.value, SecretStr):
            self.value = SecretStr(str(self.value))
        return self


class TerraformedDatabaseSettings[OutputsShape: Mapping = Mapping](
    BaseDatabaseSettings
):
    __cwd__: ClassVar[Path | None] = None
    _outputs_cache: dict[str, TerraformOutput] | None = PrivateAttr(default=None)

    @classmethod
    def set_cwd(cls, p: Path) -> None:
        cls.__cwd__ = p

    @classmethod
    def get_cwd(cls) -> Path:
        if not cls.__cwd__:
            raise ValueError(f"Cwd for {cls.__name__} was never set")
        p = cls.__cwd__
        if not p.exists():
            raise FileNotFoundError(f"Cwd for {cls.__name__} does not exist at: {p}")
        if not p.is_dir():
            raise TypeError(f"Cwd for {cls.__name__} must be a directory")
        return p

    @property
    def plan_file(self) -> Path:
        return self.get_cwd() / "main.tfplan"

    @property
    def planned(self) -> bool:
        return self.plan_file.exists()

    def tf(self, cmd: str, check: bool = True, silent: bool = False, **kwargs):
        from .typer_utils import sh
        return sh(f"terraform {cmd}", cwd=self.get_cwd(), check=check, silent=silent, text=True, **kwargs)

    def plan(self) -> subprocess.CompletedProcess:
        self.tf("init")
        return self.tf("plan -out main.tfplan")

    def apply(self):
        self.plan()
        try:
            self.tf("apply main.tfplan")
        finally:
            self.plan_file.unlink(missing_ok=True)
            self._outputs_cache = None

    def test(self) -> bool:
        try:
            self.ping()
            return True
        except Exception:
            return False

    def start(self) -> None:
        self.apply()

    def down(self) -> None:
        raise Exception(
            "Terraformed databases cannot be 'downed' like containerized databases."
        )

    def destroy(self) -> subprocess.CompletedProcess:
        typer.confirm(
            "Are you sure you want to destroy? This will permanently delete your database.",
            abort=True,
        )
        typer.confirm(
            "For realsies?",
            abort=True,
        )
        return self.tf("destroy")

    @property
    def outputs(self) -> dict[str, TerraformOutput]:
        if self._outputs_cache is None:
            r = self.tf("output -json -no-color", check=False, silent=True)
            self._outputs_cache = (
                {}
                if r.returncode != 0 or not (r.stdout or "").strip()
                else {
                    k: TerraformOutput.model_validate(v)
                    for k, v in json.loads(r.stdout).items()
                }
            )
        return self._outputs_cache

    def get_output(self, key: str) -> Any:
        outputs = self.outputs
        if key not in outputs:
            available = json.dumps(
                {
                    k: "**********" if isinstance(v.value, SecretStr) else v.value
                    for k, v in outputs.items()
                },
                indent=2,
            )
            raise TerraformOutputError(
                f"No terraform output '{key}' for '{self.get_environment_str()}'. "
                f"Available: {available or '(none - has this environment been applied?)'}"
            )
        out = outputs[key]
        return (
            out.value.get_secret_value() if isinstance(out.value, SecretStr) else out.value
        )

    @abstractmethod
    def map_outputs(self) -> None: ...

    def create_database_url(self, username: str, password: str) -> URL:
        return URL.create(
            "postgresql+psycopg",
            username=username,
            password=password,
            host=self.database_host,
            port=self.database_port,
            database=self.database_name,
        )

    @property
    def database_url(self) -> str:
        self.map_outputs()
        u = self.database_username
        p = self.database_password
        if u is None or p is None:
            raise ValueError("Expected database_user and database_password")
        return self.create_database_url(u, p).render_as_string(hide_password=False) 

    @property
    def admin_engine(self):
        from sqlalchemy import create_engine

        self.map_outputs()
        return create_engine(
            self.create_database_url(
                self.get_output("admin_username"), self.get_output("admin_password")
            ),
            connect_args={"connect_timeout": 3},
        )

    def grant(self) -> None:
        self.map_outputs()
        admin = URL.create(
            "postgresql+psycopg",
            username=self.get_output("admin_username"),
            password=self.get_output("admin_password"),
            host=self.database_host,
            port=self.database_port,
            database=self.database_name,
        )
        with create_engine(admin).begin() as c:
            c.exec_driver_sql(f'GRANT ALL ON SCHEMA public TO "{self.database_username}"')
        typer.secho(f"Ensured grant on schema public to {self.database_username}", fg=typer.colors.GREEN)

    def temp(self) -> None:
        raise Exception("Can't spin up 'temp' for a terraformed database")

    def up_steps(self) -> list[Callable]:
        return [
            self.grant,
            self.upgrade,
            self.seed,
        ]




class MigrationSettings(BaseDatabaseSettings):
    def start(self):
        from .typer_utils import run_steps, sh
        from .postgres import pull_postgres

        m = self
        run_steps(
            fns=[
                pull_postgres,
                lambda: sh(
                    f"docker run -d --name {m.database_name} -e POSTGRES_USER={m.database_username} -e POSTGRES_PASSWORD={m.database_password} -e POSTGRES_DB=migrations -p {m.database_port}:5432 --rm postgres:18-alpine",
                    check=True,
                    silent=True,
                ),
                lambda: self.ping(attempts=60),
            ],
            label="Starting Migrations Database",
        )

    def up_steps(self) -> list[Callable]:
        return []

    def down(self):
        from .typer_utils import run_steps, sh

        m = self
        run_steps(
            fns=[
                lambda: sh(f"docker rm -f {m.database_name}", check=True, silent=True)
            ],
            label="Shutting Down Migrations Database",
        )

    def destroy(self):
        return self.down()

    def test(self):  # Can't really test it no? Lol
        return True

    def get_environment_str(self) -> str:
        return 'mig'


migration_settings = MigrationSettings(
    database_host="127.0.0.1",
    database_port=5431,
    database_username="migrations",
    database_password="migrations_password",
    database_name="migrations",
)
migration_database = migration_settings.temp


class DevDatabaseSettings(BaseDatabaseSettings):
    def start(self):
        from .typer_utils import sh

        sh(f"docker compose -f {ENV_DEV_COMPOSE} up -d", check=True)

    def down(self):
        from .typer_utils import sh

        sh(f"docker compose -f {ENV_DEV_COMPOSE} down")

    def destroy(self):
        from .typer_utils import sh

        sh(f"docker compose -f {ENV_DEV_COMPOSE} down -v")

    def test(self):
        with self.temp():
            return True

    def get_environment_str(self) -> str:
        return 'dev'


dev_settings = DevDatabaseSettings(
    database_host="127.0.0.1",
    database_port=5432,
    database_name="dev_db",
    database_username="dev_user",
    database_password="dev_password",
)
dev_database = dev_settings.temp


class StagingOutputs(TypedDict):
    database_host: str
    database_port: int
    staging_name: str
    staging_username: str
    staging_password: str


class StagingDatabaseSettings(TerraformedDatabaseSettings[StagingOutputs]):
    def sanitize(self): ...

    def stage(self): ...

    def map_outputs(self):
        self.database_host = self.get_output("database_host")
        self.database_port = self.get_output("database_port")
        self.database_name = self.get_output("staging_name")
        self.database_username = self.get_output("staging_username")
        self.database_password = self.get_output("staging_password")

    def get_environment_str(self) -> str:
        return 'staging'


StagingDatabaseSettings.set_cwd(PKG_PROD)

staging_settings = StagingDatabaseSettings()


class ProdOutputs(TypedDict):
    database_host: str
    database_port: int
    prod_name: str
    prod_username: str
    prod_password: str


class ProdDatabaseSettings(TerraformedDatabaseSettings[ProdOutputs]):
    def map_outputs(self):
        self.database_host = self.get_output("database_host")
        self.database_port = self.get_output("database_port")
        self.database_name = self.get_output("prod_name")
        self.database_username = self.get_output("prod_username")
        self.database_password = self.get_output("prod_password")

    def get_environment_str(self) -> str:
        return "prod"


ProdDatabaseSettings.set_cwd(PKG_PROD)

prod_settings = ProdDatabaseSettings()

DatabaseSetting = DevDatabaseSettings | StagingDatabaseSettings | ProdDatabaseSettings | MigrationSettings


@validate_call
def get_database_setting(env: DatabaseEnvironment) -> DatabaseSetting:
    s = None
    match env:
        case "dev":
            s = dev_settings
        case "staging":
            s = staging_settings
        case "prod":
            s = prod_settings
        case "mig":
            s = migration_settings
    return s


class AlembicSettings(BaseSettings):
    env: DatabaseEnvironment = "dev"
    auto_seed: bool = True


alembic_settings = AlembicSettings()
alembic_env: DatabaseEnvironment = cast(DatabaseEnvironment, alembic_settings.env)

class RevisionError(Exception): ...

def script_dir() -> ScriptDirectory:
    return ScriptDirectory.from_config(Config("alembic.ini"))

def alembic_heads() -> list[str]:
    return list(script_dir().get_heads())

def validate_revs(revs: list[str]) -> list[str]:
    try:
        return [s.revision for s in script_dir().get_revisions(tuple(revs))]
    except CommandError as e:
        raise RevisionError(f"unknown revision(s) {revs}: {e}") from e

def is_valid_rev(rev: str) -> str:
    return validate_revs([rev])[0]

Revision = Annotated[str, BeforeValidator(is_valid_rev)]

def latest_rev() -> str:
    """The single head revision id."""
    heads = alembic_heads()
    if not heads:
        raise RevisionError("No revisions exist yet - run 'migrations init' first.")
    if len(heads) > 1:
        raise RevisionError(f"History has branched across {len(heads)} heads: {heads}")
    return heads[0]
