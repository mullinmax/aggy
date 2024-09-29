import pytest
import redis
from db.base import AggyBaseModel


def test_key_property_raises_not_implemented_error():
    """Test that accessing the 'key' property raises NotImplementedError."""
    model = AggyBaseModel()
    with pytest.raises(NotImplementedError):
        _ = model.key


def test_db_con():
    model = AggyBaseModel()

    with model.db_con() as r:
        assert isinstance(r, redis.Redis)
        r.ping()


def test_base_create_raises_not_implemented_error():
    model = AggyBaseModel()
    with pytest.raises(NotImplementedError):
        model.create()
