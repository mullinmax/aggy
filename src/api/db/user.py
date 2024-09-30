import bcrypt

from .base import AggyBaseModel
from .feed import Feed


class User(AggyBaseModel):
    name: str
    hashed_password: str = None

    @property
    def key(self):
        return f"USER:{self.name_hash}"

    @property
    def name_hash(self):
        return self.__insecure_hash__(self.name)

    @classmethod
    def hash_password(cls, password: str):
        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    @property
    def feeds_key(self):
        return f"USER:{self.name_hash}:FEEDS"

    @property
    def feed_hashes(self):
        with self.db_con() as r:
            return r.smembers(self.feeds_key)

    @property
    def feeds(self):
        return [
            Feed.read(user_hash=self.name_hash, name_hash=name_hash)
            for name_hash in self.feed_hashes
        ]

    def set_password(self, password: str):
        # TODO password complexity check
        self.hashed_password = self.hash_password(password)

    def check_password(self, password: str):
        return bcrypt.checkpw(
            password.encode("utf-8"), self.hashed_password.encode("utf-8")
        )

    def create(self):
        with self.db_con() as r:
            if self.hashed_password is None:
                raise Exception("Password is required to create a user")

            if self.exists():
                raise Exception(f"User with name {self.name} already exists")

            r.hset(self.key, mapping=self.model_dump())
            r.sadd("USERS", self.name_hash)

        return self.key

    @classmethod
    def read(cls, name_hash=None, name=None) -> "User":
        if name_hash is None:
            if name is None:
                raise Exception("name or name_hash is required")
            name_hash = User(name=name).name_hash

        with cls.db_con() as r:
            user_data = r.hgetall(f"USER:{name_hash}")

        if not user_data:
            raise Exception(f"User with name_hash {name_hash} does not exist")

        return cls(**user_data)

    @classmethod
    def read_all(cls) -> list["User"]:
        with cls.db_con() as r:
            user_hashes = r.smembers("USERS")

        if not user_hashes:
            return []

        return [cls.read(name_hash=name_hash) for name_hash in user_hashes]

    def update(self):
        with self.db_con() as r:
            if not self.exists():
                raise Exception(f"User withname {self.name} does not exist")

            r.hset(
                self.key,
                mapping=self.model_dump(),
            )

    def delete(self):
        with self.db_con() as r:
            # delete all feeds
            for feed in self.feeds:
                feed.delete()

            # remove user from list of users
            r.srem("USERS", self.name_hash)

            # delete self
            r.delete(self.key)

    def add_feed(self, feed: Feed):
        with self.db_con() as r:
            if feed.user_hash != self.name_hash:
                raise Exception("Feed does not belong to user")
            if not feed.exists():
                feed.create()
            r.sadd(self.feeds_key, feed.name_hash)

    def remove_feed(self, feed: Feed):
        with self.db_con() as r:
            # get the feed
            feed.delete()
            # delete feed
            r.srem(self.feeds_key, feed.name_hash)
