from typing import List, Union

from .base import BlinderBaseModel
from .item import ItemStrict


class ItemCollection(BlinderBaseModel):
    @property
    def items_key(self) -> str:
        raise NotImplementedError

    def query_items(self, start=0, count=-1) -> List[ItemStrict]:
        with self.db_con() as r:
            url_hashes = r.zrange(self.items_key, start, count)
        items = [ItemStrict.read(url_hash) for url_hash in url_hashes]
        items = [i for i in items if i]
        return items

    def add_items(self, items: Union[ItemStrict, List[ItemStrict]]) -> None:
        with self.db_con() as r:
            if isinstance(items, ItemStrict):
                items = [items]
            for item in items:
                r.zadd(self.items_key, {item.url_hash: 0})

    def remove_items(self, items: Union[ItemStrict, List[ItemStrict]]) -> None:
        with self.db_con() as r:
            if isinstance(items, ItemStrict):
                items = [items]
            for item in items:
                r.zrem(self.items_key, item.url_hash)
