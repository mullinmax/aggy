from .base import r


def init_db():
    r.set("SCHEMA_VERSION", "1.0.0")
