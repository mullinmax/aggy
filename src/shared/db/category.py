from pydantic import constr
from typing import List
from flask import current_app

from .base import BlinderBaseModel, r
from .item import ItemStrict

class Category(BlinderBaseModel):
    user_hash: str
    name: constr(strict=True, min_length=1)
    name_hash: str = ""  # generated if not provided

    @property
    def __key__(self):
        if not self.name_hash:
            self.name_hash = hashlib.sha256(self.name.encode()).hexdigest()
        return f"USER:{self.user_hash}:CATEGORY:{self.name_hash}"

    def create(self):
        category_key = self.__key__
        
        if r.exists(category_key):
            raise Exception(f"Category with name {self.name} already exists")    

        r.hset(category_key, mapping={'name': self.name, 'user_hash': self.user_hash})
        r.sadd(f"USER:{self.user_hash}:CATEGORIES", self.name_hash)
        
        return category_key

    @classmethod
    def read(cls, user_hash, name_hash):
        category_data = r.hgetall(f"USER:{user_hash}:CATEGORY:{name_hash}")
        current_app.logger.info(category_data)
        if category_data:
            return Category(**category_data, name_hash=name_hash)
        else:
            raise Exception("Category does not exist")

    @classmethod
    def read_all(cls, user_hash) -> List['Category']:
        category_name_hashs = r.smembers(f"USER:{user_hash}:CATEGORIES")
        categories = []
        for name_hash in category_name_hashs:
            categories.append(cls.read(user_hash, name_hash))
        return categories

    def get_all_items(self):
        current_app.logger.info(f'getting all items in {self.__key__}')
        url_hashes = r.zrange(f'{self.__key__}:ITEMS', 0, -1)
        current_app.logger.info(f'{url_hashes=}')
        items = [ItemStrict.read(url_hash) for url_hash in url_hashes]
        current_app.logger.info(f'number of items recovered: {len(items)}')
        return items