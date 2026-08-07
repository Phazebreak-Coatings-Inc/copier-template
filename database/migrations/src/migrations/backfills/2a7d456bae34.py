from database_core import backfill
from sqlmodel import Session


@backfill("2a7d456bae34")
def backfill_2a7d456bae34(session: Session) -> None:
    print("my first backfill")
    ...
