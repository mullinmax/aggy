import bcrypt
from datetime import datetime
import hashlib


from .base import BlinderBaseModel
from .category import Category


class User(BlinderBaseModel):
    username: str
    hashed_password: str
    is_superuser: bool = False
    created_at: datetime = datetime.now()
    updated_at: datetime = datetime.now()

    @property
    def key(self):
        return f"USER:{self.username}"

    @property
    def user_hash(self):
        return hashlib.sha256(self.username.encode()).hexdigest()

    @classmethod
    def hash_password(cls, password: str):
        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    @property
    def categories_key(self):
        return f"USER:{self.user_hash}:CATEGORIES"

    @property
    def categories(self):
        with self.redis_con() as r:
            return [
                Category.read(user_hash=self.user_hash, name_hash=name_hash)
                for name_hash in r.smembers(self.categories_key)
            ]

    def set_password(self, password: str):
        self.hashed_password = self.hash_password(password)

    def check_password(self, password: str):
        return bcrypt.checkpw(
            password.encode("utf-8"), self.hashed_password.encode("utf-8")
        )

    def create(self):
        with self.redis_con() as r:
            if self.exists():
                raise Exception(f"User with username {self.username} already exists")

            if self.hash_password is None:
                raise Exception("Password is required to create a user")

            r.hset(
                self.key,
                mapping=self.model_dump_json(),
            )

        return self.key

    @classmethod
    def read(cls, username: str):
        with cls.redis_con() as r:
            user_data = r.hgetall(f"USER:{username}")

        if not user_data:
            raise Exception(f"User with username {username} does not exist")

        return cls(**user_data)

    def update(self):
        with self.redis_con() as r:
            if not self.exists():
                raise Exception(f"User with username {self.username} does not exist")

            r.hset(
                self.key,
                mapping=self.model_dump_json(),
            )

    def delete(self):
        with self.redis_con() as r:
            # delete all categories
            for category in self.categories:
                category.delete()

            # delete self
            r.delete(self.key)
