import bcrypt
from datetime import datetime
import hashlib
from pydantic import field_serializer

from .base import BlinderBaseModel
from .category import Category


class User(BlinderBaseModel):
    name: str
    hashed_password: str = None
    created: datetime = datetime.now()
    updated: datetime = datetime.now()

    @property
    def key(self):
        return f"USER:{self.name}"

    @property
    def name_hash(self):
        return hashlib.sha256(self.name.encode()).hexdigest()

    @classmethod
    def hash_password(cls, password: str):
        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    @property
    def categories_key(self):
        return f"USER:{self.name_hash}:CATEGORIES"

    @property
    def category_hashes(self):
        with self.redis_con() as r:
            return r.smembers(self.categories_key)

    @property
    def categories(self):
        return [
            Category.read(user_hash=self.name_hash, name_hash=name_hash)
            for name_hash in self.category_hashes
        ]

    def set_password(self, password: str):
        # TODO password complexity check
        self.hashed_password = self.hash_password(password)

    def check_password(self, password: str):
        return bcrypt.checkpw(
            password.encode("utf-8"), self.hashed_password.encode("utf-8")
        )

    def create(self):
        with self.redis_con() as r:
            if self.hashed_password is None:
                raise Exception("Password is required to create a user")

            if self.exists():
                raise Exception(f"User with name {self.name} already exists")

            self.created = max(self.created, self.updated)
            self.updated = self.created

            r.hset(self.key, mapping=self.model_dump())

        return self.key

    @classmethod
    def read(cls, name: str):
        with cls.redis_con() as r:
            user_data = r.hgetall(f"USER:{name}")

        if not user_data:
            raise Exception(f"User with name {name} does not exist")

        return cls(**user_data)

    def update(self):
        with self.redis_con() as r:
            if not self.exists():
                raise Exception(f"User withname {self.name} does not exist")

            self.updated = datetime.now()

            r.hset(
                self.key,
                mapping=self.model_dump(),
            )

    def delete(self):
        with self.redis_con() as r:
            # delete all categories
            for category in self.categories:
                category.delete()

            # delete self
            r.delete(self.key)

    def add_category(self, category: Category):
        with self.redis_con() as r:
            if category.user_hash != self.name_hash:
                raise Exception("Category does not belong to user")
            if not category.exists():
                category.create()
            r.sadd(self.categories_key, category.name_hash)

    def remove_category(self, category: Category):
        with self.redis_con() as r:
            # get the category
            category.delete()
            # delete category
            r.srem(self.categories_key, category.name_hash)

    @field_serializer("created")
    def created_at_to_str(created: datetime):
        return created.strftime("%Y-%m-%d %H:%M:%S")

    @field_serializer("updated")
    def updated_at_to_str(updated: datetime):
        return updated.strftime("%Y-%m-%d %H:%M:%S")
