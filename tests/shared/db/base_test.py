import pytest
from redislite import Redis as redis_lite
from src.shared.db.base import BlinderBaseModel, get_redis_connection


def test_key_property_raises_not_implemented_error():
    """Test that accessing the 'key' property raises NotImplementedError."""
    model = BlinderBaseModel()
    with pytest.raises(NotImplementedError):
        _ = model.key


def test_redis_connection_in_test_mode():
    r = get_redis_connection()
    assert isinstance(r, redis_lite), "Should use redislite in testing mode"
