from typing import List, Union

from .base import AggyBaseModel
from .item import ItemStrict
from utils import skip_limit_to_start_end


class ItemCollection(AggyBaseModel):
    @property
    def items_key(self) -> str:
        raise NotImplementedError

    def query_items(self, skip=None, limit=None) -> List[ItemStrict]:
        start, end = skip_limit_to_start_end(skip, limit)
        with self.db_con() as r:
            url_hashes = r.zrange(self.items_key, start=start, end=end)
        items = [ItemStrict.read(url_hash) for url_hash in url_hashes]
        items = [i for i in items if i]
        return items

    def add_items(self, items: Union[ItemStrict, List[ItemStrict]]) -> None:
        if isinstance(items, ItemStrict):
            items = {items.url_hash: 0}
        elif isinstance(items, list):
            items = {item.url_hash: 0 for item in items}
        else:
            raise ValueError(f"Invalid type for items: {type(items)}")

        with self.db_con() as r:
            r.zadd(self.items_key, items)

    def set_items_scores(self, items: dict[str, int]) -> None:
        with self.db_con() as r:
            r.zadd(self.items_key, items)

    def remove_items(self, items: Union[ItemStrict, List[ItemStrict]]) -> None:
        with self.db_con() as r:
            if isinstance(items, ItemStrict):
                items = [items]
            for item in items:
                r.zrem(self.items_key, item.url_hash)

    def count_items(self) -> int:
        with self.db_con() as r:
            return r.zcard(self.items_key)
