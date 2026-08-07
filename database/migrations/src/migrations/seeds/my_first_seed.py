from database_core import seed
from models import *
from sqlmodel import Session


@seed(["dev"])
def my_first_seed(session: Session) -> None: ...
