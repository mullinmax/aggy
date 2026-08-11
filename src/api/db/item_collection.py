from typing import List, Union

from .base import AggyBaseModel
from .item import ItemStrict


class ItemCollection(AggyBaseModel):
    """Mixin for objects that own an ordered set of items.

    Subclasses must implement ``_items_filter`` returning a SQL fragment and
    parameter tuple identifying the rows in the join table that belong to
    this collection, and ``_items_table`` naming the join table itself.
    """

    @property
    def _items_table(self) -> str:
        raise NotImplementedError

    def _items_filter(self) -> tuple[str, tuple]:
        raise NotImplementedError

    def query_items(self, skip=None, limit=None) -> List[ItemStrict]:
        where, params = self._items_filter()
        sql = (
            f"SELECT i.* FROM items i "
            f"JOIN {self._items_table} c ON c.item_url_hash = i.url_hash "
            f"WHERE {where} "
            f"ORDER BY c.score DESC, c.added_at DESC"
        )
        if limit is not None and limit >= 0:
            sql += " LIMIT %s"
            params = params + (limit,)
        if skip is not None and skip > 0:
            sql += " OFFSET %s"
            params = params + (skip,)

        with self.db_con() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

        return [ItemStrict.from_row(row) for row in rows if row]

    def add_items(self, items: Union[ItemStrict, List[ItemStrict]]) -> None:
        """Link items to this collection, leaving any already linked alone.

        Adding is not scoring: an item this collection already holds keeps the
        score ranking gave it. Ingest re-links every entry it sees on every
        check (that's how an item another feed scraped first gets attached),
        so overwriting here would reset the whole feed to zero each pass.
        """
        if isinstance(items, ItemStrict):
            items = [items]
        if not isinstance(items, list):
            raise ValueError(f"Invalid type for items: {type(items)}")

        self._upsert_items_scores(
            {item.url_hash: 0 for item in items}, overwrite=False
        )

    def set_items_scores(self, items: dict[str, float]) -> None:
        self._upsert_items_scores(items, overwrite=True)

    def _upsert_items_scores(self, items: dict[str, float], overwrite: bool) -> None:
        if not items:
            return
        cols, key_params = self._collection_keys()
        placeholders = ", ".join(["(" + ", ".join(["%s"] * (len(cols) + 2)) + ")"] * len(items))
        params: list = []
        for url_hash, score in items.items():
            params.extend(key_params)
            params.append(url_hash)
            params.append(float(score))
        col_list = ", ".join(cols + ["item_url_hash", "score"])
        conflict = (
            "DO UPDATE SET score = EXCLUDED.score" if overwrite else "DO NOTHING"
        )
        sql = (
            f"INSERT INTO {self._items_table} ({col_list}) VALUES {placeholders} "
            f"ON CONFLICT ({', '.join(cols + ['item_url_hash'])}) {conflict}"
        )
        with self.db_con() as cur:
            cur.execute(sql, params)

    def remove_items(self, items: Union[ItemStrict, List[ItemStrict]]) -> None:
        if isinstance(items, ItemStrict):
            items = [items]
        where, params = self._items_filter()
        with self.db_con() as cur:
            for item in items:
                cur.execute(
                    f"DELETE FROM {self._items_table} "
                    f"WHERE {where} AND item_url_hash = %s",
                    params + (item.url_hash,),
                )

    def count_items(self) -> int:
        where, params = self._items_filter()
        with self.db_con() as cur:
            cur.execute(
                f"SELECT COUNT(*) AS n FROM {self._items_table} WHERE {where}",
                params,
            )
            return cur.fetchone()["n"]

    def _collection_keys(self) -> tuple[list[str], tuple]:
        """Return the column list and corresponding values that identify this
        collection in its items join table."""
        raise NotImplementedError
