from datetime import datetime
from pydantic import confloat

from .item import ItemLoose
from .user import User
from .feed import Feed
from .base import AggyBaseModel

# class ReservedVoteReasons(Enum):
# leaving unimplemented for now, should allow arbitrary user-defined reasons (like tags)
# For now a simple down vote is plenty
#   REPETITIVE = 2 # 🔁
#   NSFW = 3 # 🍑
#   NSFL = 4 # 🤮
#   SCARY = 5 # 🙈
#   IRRELEVANT = 7 # 🤷
#   OUTDATED = 9 # 🕰️
#   LOW_QUALITY = 8 # 🗑️
#   MISLEADING = 6 # 🤥
#   OFFENSIVE = 10 # 🤡
#   PROMOTIONAL = 11 # 📢


class ItemState(AggyBaseModel):
    item_url_hash: str
    user_hash: str
    feed_hash: str
    score: confloat(ge=-1, le=1) = None
    score_date: datetime = None
    is_read: bool = None

    @property
    def key(self) -> str:
        return f"USER:{self.user_hash}:FEED:{self.feed_hash}:ITEM:{self.item_url_hash}:ITEM_STATE"

    def exists(self) -> bool:
        with self.db_con() as cur:
            cur.execute(
                "SELECT 1 FROM item_states "
                "WHERE user_hash = %s AND feed_hash = %s AND item_url_hash = %s",
                (self.user_hash, self.feed_hash, self.item_url_hash),
            )
            return cur.fetchone() is not None

    def create(self) -> None:
        # check user exists (raises if missing)
        User.read(self.user_hash)

        feed = Feed.read(user_hash=self.user_hash, name_hash=self.feed_hash)
        if not feed:
            raise ValueError(f"Feed with hash {self.feed_hash} does not exist")

        item = ItemLoose.read(self.item_url_hash)
        if not item:
            raise ValueError(f"Item with hash {self.item_url_hash} does not exist")

        with self.db_con() as cur:
            cur.execute(
                "INSERT INTO item_states (user_hash, feed_hash, item_url_hash, "
                "score, score_date, is_read) VALUES (%s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (user_hash, feed_hash, item_url_hash) DO UPDATE SET "
                "score = EXCLUDED.score, score_date = EXCLUDED.score_date, "
                "is_read = EXCLUDED.is_read",
                (
                    self.user_hash,
                    self.feed_hash,
                    self.item_url_hash,
                    self.score,
                    self.score_date,
                    self.is_read,
                ),
            )

    def update(self) -> None:
        self.create()

    def delete(self) -> None:
        with self.db_con() as cur:
            cur.execute(
                "DELETE FROM item_states "
                "WHERE user_hash = %s AND feed_hash = %s AND item_url_hash = %s",
                (self.user_hash, self.feed_hash, self.item_url_hash),
            )

    @classmethod
    def read(cls, user_hash, feed_hash, item_url_hash) -> "ItemState":
        with cls.db_con() as cur:
            cur.execute(
                "SELECT score, score_date, is_read FROM item_states "
                "WHERE user_hash = %s AND feed_hash = %s AND item_url_hash = %s",
                (user_hash, feed_hash, item_url_hash),
            )
            row = cur.fetchone()

        if not row:
            return None

        return cls(
            user_hash=user_hash,
            feed_hash=feed_hash,
            item_url_hash=item_url_hash,
            score=row["score"],
            score_date=row["score_date"],
            is_read=row["is_read"],
        )

    @classmethod
    def set_state(
        cls,
        user_hash: str,
        feed_hash: str,
        item_url_hash: str,
        score: confloat(ge=-1, le=1) = None,
        is_read: bool = None,
    ) -> None:
        item_state = cls.read(user_hash, feed_hash, item_url_hash)

        if item_state is None:
            item_state = cls(
                item_url_hash=item_url_hash,
                user_hash=user_hash,
                feed_hash=feed_hash,
            )

        if score is not None:
            item_state.score = score
            item_state.score_date = datetime.now()

        if is_read is not None:
            item_state.is_read = is_read

        item_state.update()
