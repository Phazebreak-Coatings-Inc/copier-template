from abc import ABC
from typing import Self

from sqlmodel import Field, SQLModel


class CreateMixin(ABC):
    created_by: str | None = Field()
    last_modified_by: str | None = Field()

    @classmethod
    def create(cls, username: str = "Anonymous", **kwargs) -> Self:
        return cls(created_by=username, **kwargs)  # type: ignore


class SQLModelBase(SQLModel, CreateMixin, ABC): ...
