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
    def feeds(self):
        return Feed.read_all(user_hash=self.name_hash)

    @property
    def feed_hashes(self):
        return {f.name_hash for f in self.feeds}

    def set_password(self, password: str):
        # TODO password complexity check
        self.hashed_password = self.hash_password(password)

    def check_password(self, password: str):
        return bcrypt.checkpw(
            password.encode("utf-8"), self.hashed_password.encode("utf-8")
        )

    def exists(self) -> bool:
        with self.db_con() as cur:
            cur.execute(
                "SELECT 1 FROM users WHERE name_hash = %s", (self.name_hash,)
            )
            return cur.fetchone() is not None

    def create(self):
        if self.hashed_password is None:
            raise Exception("Password is required to create a user")

        if self.exists():
            raise Exception(f"User with name {self.name} already exists")

        with self.db_con() as cur:
            cur.execute(
                "INSERT INTO users (name_hash, name, hashed_password) "
                "VALUES (%s, %s, %s)",
                (self.name_hash, self.name, self.hashed_password),
            )

        return self.key

    @classmethod
    def read(cls, name_hash=None, name=None) -> "User":
        if name_hash is None:
            if name is None:
                raise Exception("name or name_hash is required")
            name_hash = User(name=name).name_hash

        with cls.db_con() as cur:
            cur.execute(
                "SELECT name, hashed_password FROM users WHERE name_hash = %s",
                (name_hash,),
            )
            row = cur.fetchone()

        if not row:
            raise Exception(f"User with name_hash {name_hash} does not exist")

        return cls(name=row["name"], hashed_password=row["hashed_password"])

    @classmethod
    def read_all(cls) -> list["User"]:
        with cls.db_con() as cur:
            cur.execute("SELECT name, hashed_password FROM users")
            rows = cur.fetchall()

        return [
            cls(name=row["name"], hashed_password=row["hashed_password"])
            for row in rows
        ]

    def update(self):
        if not self.exists():
            raise Exception(f"User withname {self.name} does not exist")

        with self.db_con() as cur:
            cur.execute(
                "UPDATE users SET name = %s, hashed_password = %s "
                "WHERE name_hash = %s",
                (self.name, self.hashed_password, self.name_hash),
            )

    def delete(self):
        # ON DELETE CASCADE on feeds (and their dependents) handles cleanup.
        with self.db_con() as cur:
            cur.execute("DELETE FROM users WHERE name_hash = %s", (self.name_hash,))

    def add_feed(self, feed: Feed):
        if feed.user_hash != self.name_hash:
            raise Exception("Feed does not belong to user")
        if not feed.exists():
            feed.create()

    def remove_feed(self, feed: Feed):
        feed.delete()
