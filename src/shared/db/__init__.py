
from pydantic import BaseModel, HttpUrl, constr, ValidationError
from uuid import uuid4
from typing import List, Set
import hashlib
from flask import current_app
from datetime import datetime

from shared.db.category import Category
from shared.db.feed import Feed
from shared.db.item import Item
from shared.db.base import r, BlinderBaseModel

def init_db():
    r.set("SCHEMA_VERSION", "1.0.0")
