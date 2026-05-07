import pytest

from db.base import AggyBaseModel, get_db_con


def test_key_property_raises_not_implemented_error():
    """Test that accessing the 'key' property raises NotImplementedError."""
    model = AggyBaseModel()
    with pytest.raises(NotImplementedError):
        _ = model.key


def test_db_con():
    with get_db_con() as cur:
        cur.execute("SELECT 1 AS one")
        row = cur.fetchone()
        assert row["one"] == 1


def test_base_create_raises_not_implemented_error():
    model = AggyBaseModel()
    with pytest.raises(NotImplementedError):
        model.create()
