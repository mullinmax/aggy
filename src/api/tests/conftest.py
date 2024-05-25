# fixtures
from tests.fixtures.category import unique_category, existing_category  # noqa
from tests.fixtures.item import unique_item_strict, existing_item_strict  # noqa
from tests.fixtures.feed import unique_feed, existing_feed  # noqa
from tests.fixtures.user import unique_user, existing_user  # noqa
from tests.fixtures.client import client  # noqa
from tests.fixtures.token import token  # noqa

from db.base import db_init

db_init()
