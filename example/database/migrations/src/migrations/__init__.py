from pathlib import Path

from sqlmodel import SQLModel

from .backfills import *
from .seeds import *

APP_METADATA = SQLModel.metadata
