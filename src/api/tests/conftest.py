# fixtures
from tests.fixtures.category import unique_category  # noqa
from tests.fixtures.item import unique_item_strict  # noqa
from tests.fixtures.feed import unique_feed  # noqa
from tests.fixtures.user import unique_user  # noqa
from tests.fixtures.client import client  # noqa

from db.base import db_init

db_init()
