import pytest
import redis
from db.base import BlinderBaseModel


def test_key_property_raises_not_implemented_error():
    """Test that accessing the 'key' property raises NotImplementedError."""
    model = BlinderBaseModel()
    with pytest.raises(NotImplementedError):
        _ = model.key


def test_db_con():
    model = BlinderBaseModel()

    with model.db_con() as r:
        assert isinstance(r, redis.Redis)
        r.ping()


def test_base_create_raises_not_implemented_error():
    model = BlinderBaseModel()
    with pytest.raises(NotImplementedError):
        model.create()
