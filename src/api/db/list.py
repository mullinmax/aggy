from typing import List, Optional

from pydantic import StringConstraints
from typing_extensions import Annotated

from .base import AggyBaseModel
from .item import ItemStrict
from .user import User


class UserList(AggyBaseModel):
    """A user-owned, playlist-like collection of items.

    Lists span feeds: any item may belong to any number of a user's lists.
    Membership doubles as a positive ranking signal (see ranking/engine.py).
    """

    user_hash: str
    name: Annotated[str, StringConstraints(strict=True, min_length=1)]

    @property
    def key(self):
        return f"USER:{self.user_hash}:LIST:{self.name_hash}"

    @property
    def name_hash(self):
        return self.__insecure_hash__(self.name)

    def exists(self) -> bool:
        with self.db_con() as cur:
            cur.execute(
                "SELECT 1 FROM lists WHERE user_hash = %s AND name_hash = %s",
                (self.user_hash, self.name_hash),
            )
            return cur.fetchone() is not None

    def create(self):
        # check the owner exists (raises if missing)
        User.read(self.user_hash)

        if self.exists():
            raise ValueError(f"List with name {self.name} already exists")

        with self.db_con() as cur:
            cur.execute(
                "INSERT INTO lists (user_hash, name_hash, name) VALUES (%s, %s, %s)",
                (self.user_hash, self.name_hash, self.name),
            )

        return self.key

    def delete(self):
        # ON DELETE CASCADE removes this list's memberships.
        with self.db_con() as cur:
            cur.execute(
                "DELETE FROM lists WHERE user_hash = %s AND name_hash = %s",
                (self.user_hash, self.name_hash),
            )

    def item_count(self) -> int:
        with self.db_con() as cur:
            cur.execute(
                "SELECT COUNT(*) AS n FROM list_items "
                "WHERE user_hash = %s AND list_hash = %s",
                (self.user_hash, self.name_hash),
            )
            return cur.fetchone()["n"]

    def contains(self, item_url_hash: str) -> bool:
        with self.db_con() as cur:
            cur.execute(
                "SELECT 1 FROM list_items "
                "WHERE user_hash = %s AND list_hash = %s AND item_url_hash = %s",
                (self.user_hash, self.name_hash, item_url_hash),
            )
            return cur.fetchone() is not None

    def add_item(self, item_url_hash: str) -> None:
        with self.db_con() as cur:
            cur.execute(
                "INSERT INTO list_items (user_hash, list_hash, item_url_hash) "
                "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                (self.user_hash, self.name_hash, item_url_hash),
            )

    def remove_item(self, item_url_hash: str) -> None:
        with self.db_con() as cur:
            cur.execute(
                "DELETE FROM list_items "
                "WHERE user_hash = %s AND list_hash = %s AND item_url_hash = %s",
                (self.user_hash, self.name_hash, item_url_hash),
            )

    def items(self) -> List[ItemStrict]:
        with self.db_con() as cur:
            cur.execute(
                "SELECT i.* FROM items i "
                "JOIN list_items li ON li.item_url_hash = i.url_hash "
                "WHERE li.user_hash = %s AND li.list_hash = %s "
                "ORDER BY li.added_at DESC",
                (self.user_hash, self.name_hash),
            )
            rows = cur.fetchall()
        return [ItemStrict.from_row(row) for row in rows if row]

    @classmethod
    def read(cls, user_hash, name_hash) -> Optional["UserList"]:
        with cls.db_con() as cur:
            cur.execute(
                "SELECT name FROM lists WHERE user_hash = %s AND name_hash = %s",
                (user_hash, name_hash),
            )
            row = cur.fetchone()

        if row:
            return cls(user_hash=user_hash, name=row["name"])
        return None

    @classmethod
    def read_all(cls, user_hash) -> List["UserList"]:
        with cls.db_con() as cur:
            cur.execute(
                "SELECT name FROM lists WHERE user_hash = %s ORDER BY name",
                (user_hash,),
            )
            rows = cur.fetchall()
        return [cls(user_hash=user_hash, name=row["name"]) for row in rows]

    @classmethod
    def set_item_membership(
        cls, user_hash: str, item_url_hash: str, list_hashes: List[str]
    ) -> None:
        """Make the item belong to exactly ``list_hashes`` (of the user's own
        lists) and no others — the "submit" from the add-to-list checklist.

        Hashes that don't name one of the user's lists are ignored.
        """
        wanted = set(list_hashes or [])
        owned = {lst.name_hash for lst in cls.read_all(user_hash)}
        wanted &= owned

        with cls.db_con() as cur:
            # drop memberships the user unchecked
            cur.execute(
                "DELETE FROM list_items "
                "WHERE user_hash = %s AND item_url_hash = %s",
                (user_hash, item_url_hash),
            )
            for list_hash in wanted:
                cur.execute(
                    "INSERT INTO list_items (user_hash, list_hash, item_url_hash) "
                    "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                    (user_hash, list_hash, item_url_hash),
                )
