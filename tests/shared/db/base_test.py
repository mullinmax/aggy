import pytest
import redis
from src.shared.db.base import BlinderBaseModel


def test_key_property_raises_not_implemented_error():
    """Test that accessing the 'key' property raises NotImplementedError."""
    model = BlinderBaseModel()
    with pytest.raises(NotImplementedError):
        _ = model.key


def test_redis_con():
    model = BlinderBaseModel()

    with model.redis_con() as r:
        assert isinstance(r, redis.Redis)
        # r.ping()