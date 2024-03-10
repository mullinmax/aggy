
from pydantic import BaseModel, HttpUrl, constr, ValidationError
from uuid import uuid4
from typing import List, Set
import hashlib
from flask import current_app
from datetime import datetime

from .category import Category
from .feed import Feed
from .item import ItemStrict, ItemLoose, ItemBase
from .base import r, BlinderBaseModel

def init_db():
    r.set("SCHEMA_VERSION", "1.0.0")
