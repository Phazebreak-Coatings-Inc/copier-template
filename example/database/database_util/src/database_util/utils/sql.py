import ast
import copy
from pathlib import Path
from typing import Literal

import inflection
import sqlglot
from sqlacodegen.generators import SQLModelGenerator
from sqlalchemy import MetaData, create_mock_engine
from sqlglot import exp

from . import (
    PKG_MODELS,
    TABLES_SQL,
    ruff_format,
)
from . import (
    migration_database as mdb,
)
from . import (
    migration_settings as m,
)

FileKind = Literal["base", "mixin", "model"]


class Model:
    def __init__(self, class_def: ast.ClassDef):
        self.cls = class_def

    @property
    def name(self) -> str:
        return self.cls.name

    def get_path(self, file: FileKind):
        return PKG_MODELS / inflection.underscore(self.name) / f"{file}.py"

    @property
    def fields(self) -> list[ast.AnnAssign]:
        return [
            s
            for s in self.cls.body
            if isinstance(s, ast.AnnAssign) and isinstance(s.target, ast.Name)
        ]

    @staticmethod
    def is_relationship(field: ast.AnnAssign) -> bool:
        return (
            isinstance(field.value, ast.Call)
            and isinstance(field.value.func, ast.Name)
            and field.value.func.id == "Relationship"
        )

    @property
    def relationships(self) -> list[ast.AnnAssign]:
        return [f for f in self.fields if self.is_relationship(f)]

    def relationship_targets(self, known: set[str]) -> set[str]:
        out: set[str] = set()
        for f in self.relationships:
            for n in ast.walk(f.annotation):
                if isinstance(n, ast.Name) and n.id in known:
                    out.add(n.id)
                elif isinstance(n, ast.Constant) and n.value in known:
                    out.add(n.value)
        return out - {self.name}

    def class_to_mixin(self) -> str:
        return f"class {self.name}Mixin: ...\n"

    def class_to_model(self, known: set[str]) -> str:
        lines = [
            "from typing import TYPE_CHECKING, List, Optional",
            "from sqlmodel import Relationship",
            "from ..base_model import SQLModelBase",
            f"from .base import {self.name}Base",
            f"from .mixin import {self.name}Mixin",
        ]
        if targets := sorted(self.relationship_targets(known)):
            lines += ["", "if TYPE_CHECKING:"] + [
                f"    from ..{inflection.underscore(t)}.model import {t}"
                for t in targets
            ]
        lines += [
            "",
            "",
            f"class {self.name}({self.name}Mixin, SQLModelBase, {self.name}Base, table=True):",
        ]
        lines += [f"    {ast.unparse(r)}" for r in self.relationships] or ["    pass"]
        return "\n".join(lines) + "\n"

    def class_to_base(self) -> str:
        """SQLModel base: the same class without table=True or relationships."""
        node = copy.deepcopy(self.cls)
        node.name = f"{self.name}Base"
        node.keywords = [k for k in node.keywords if k.arg != "table"]
        node.decorator_list = []
        node.body = [
            s
            for s in node.body
            if not (isinstance(s, ast.AnnAssign) and self.is_relationship(s))
        ] or [ast.Pass()]
        return "from sqlmodel import SQLModel, Field\n\n\n" + ast.unparse(node)

    def class_to_init(self) -> str:
        names = [
            f"{self.name}Base",
            self.name,
        ]
        imports = f"from .base import {names[0]}\nfrom .model import {names[1]}\n"
        exports = "__all__ = [" + ", ".join(f'"{n}"' for n in names) + "]\n"
        return imports + "\n" + exports


class SQLGenerator:
    def __init__(self, dry_run: bool = False):
        g = SQLModelGenerator
        e = m.engine
        with mdb():
            with e.begin() as c:
                c.exec_driver_sql(self.tables_file.read_text())

            md = MetaData()
            md.reflect(bind=e)
            self.code = ruff_format(g(md, e, options=[]).generate())

    @property
    def tables_file(self) -> Path:
        return TABLES_SQL

    @property
    def tree(self) -> ast.Module:
        return ast.parse(self.code)

    @property
    def models(self):
        return [Model(n) for n in self.tree.body if isinstance(n, ast.ClassDef)]

    @property
    def len_models(self) -> int:
        return len(self.models)

    @property
    def header(self) -> str:
        return "\n".join(
            ast.get_source_segment(self.code, n) or ""
            for n in self.tree.body
            if isinstance(n, (ast.Import, ast.ImportFrom))
        )

    def write_files(self):
        known = {m.name for m in self.models}
        for model in self.models:
            directory = model.get_path("model").parent
            directory.mkdir(parents=True, exist_ok=True)

            model.get_path("base").write_text(
                ruff_format(f"{self.header}\n\n\n{model.class_to_base()}")
            )
            model.get_path("model").write_text(ruff_format(model.class_to_model(known)))

            mixin_path = model.get_path("mixin")
            if not mixin_path.exists():
                mixin_path.write_text(ruff_format(model.class_to_mixin()))

            (directory / "__init__.py").write_text(ruff_format(model.class_to_init()))


DIALECT = "postgres"


class SQLParseError(Exception): ...


def get_creates(sql: str) -> list[exp.Create]:
    return [s for s in sqlglot.parse(sql) if isinstance(s, exp.Create)]


def create_to_columns(create: exp.Create) -> list[exp.ColumnDef]:
    return list(create.find_all(exp.ColumnDef))


def create_to_table(create: exp.Create) -> exp.Table:
    return create.this.find(exp.Table)


class SQLMergeError(Exception): ...


def as_comment(col: exp.ColumnDef) -> exp.ColumnDef:
    setattr(col, "_commented", True)
    return col


def is_comment(col: exp.ColumnDef) -> bool:
    return getattr(col, "_commented", False)


def merge_columns(
    c1: list[exp.ColumnDef],
    c2: list[exp.ColumnDef],
    comment: bool = True,
):
    names = {c.name for c in c1}
    merged = []
    for col in c2:
        if col.name in names:
            raise SQLMergeError(f"Column '{col.name}' is already defined")
        merged.append(as_comment(col) if comment else col)
    return merged


def render_create(table: str, cols: list[exp.ColumnDef]) -> str:
    real = [c for c in cols if not is_comment(c)]
    commented = [c for c in cols if is_comment(c)]
    body = ",\n  ".join(c.sql(dialect=DIALECT) for c in real)
    out = f"CREATE TABLE {table} (\n  {body}"
    if commented:
        out += "\n  " + "\n  ".join("-- " + c.sql(dialect=DIALECT) for c in commented)
    return out + "\n)"


def get_sql_from_orm(metadata: MetaData):
    ddl = []
    engine = create_mock_engine(
        "postgresql://",
        lambda sql, *a, **k: ddl.append(str(sql.compile(dialect=engine.dialect))),
    )
    metadata.create_all(engine, checkfirst=False)
    return ddl


def comment_out(sql: str) -> str:
    return "\n".join(f"-- {line}" for line in sql.splitlines())


class SQLReverseGenerator:
    def __init__(self, metadata: MetaData):
        self.metadata = metadata

    @property
    def orm_creates(self) -> dict[str, exp.Create]:
        creates = {}
        for ddl in get_sql_from_orm(self.metadata):
            for c in get_creates(ddl):
                creates[create_to_table(c).name] = c
        return creates

    @property
    def sql_creates(self) -> dict[str, exp.Create]:
        return {create_to_table(c).name: c for c in get_creates(TABLES_SQL.read_text())}

    def reverse_table(self, table: str) -> str:
        sql_cols = create_to_columns(self.sql_creates[table])
        sql_names = {c.name for c in sql_cols}
        orm_only = [
            c
            for c in create_to_columns(self.orm_creates[table])
            if c.name not in sql_names
        ]
        return render_create(table, sql_cols + merge_columns(sql_cols, orm_only))

    def generate(self) -> dict[str, str]:
        orm = self.orm_creates
        out = {t: self.reverse_table(t) for t in self.sql_creates if t in orm}
        for t, create in orm.items():
            if t not in self.sql_creates:
                out[t] = comment_out(create.sql(dialect=DIALECT, pretty=True))
        return out

    def write(self, path: Path = TABLES_SQL, dry_run: bool = False) -> str:
        extra = [
            s
            for s in sqlglot.parse(path.read_text())
            if s is not None and not isinstance(s, exp.Create)
        ]
        if extra:
            raise SQLParseError(
                f"{path.name} contains {len(extra)} non-CREATE statement(s) that would be "
                f"lost: {[s.sql(dialect=DIALECT)[:40] for s in extra]}"
            )

        if not self.sql_creates:
            raise SQLParseError(f"No CREATE TABLE statements found in {path}")

        reversed = self.generate()
        ordered = list(self.sql_creates) + [
            t for t in reversed if t not in self.sql_creates
        ]

        parts = []
        for t in ordered:
            sql = reversed.get(t) or self.sql_creates[t].sql(
                dialect=DIALECT, pretty=True
            )
            parts.append(sql if sql.lstrip().startswith("--") else sql + ";")
        body = "\n\n".join(parts) + "\n"

        if not dry_run:
            path.write_text(body)

        return body
