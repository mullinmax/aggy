from datetime import datetime, timedelta
from pydantic import confloat
from typing import Optional

from .item import ItemLoose
from .user import User
from .feed import Feed
from .base import AggyBaseModel
from config import config

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
    score_estimate: Optional[float] = None
    score_estimate_date: Optional[datetime] = None

    @property
    def key(self) -> str:
        return f"USER:{self.user_hash}:FEED:{self.feed_hash}:ITEM:{self.item_url_hash}:ITEM_STATE"

    @property
    def score_estimate_is_stale(self):
        if not self.score_estimate_date:
            return True

        ttl = config.get("SCORE_ESTIMATE_REFRESH_HOURS")
        return self.score_estimate_date > datetime.now() + timedelta(hours=ttl)

    def create(self) -> None:
        with self.db_con() as r:
            # check user exists
            User.read(self.user_hash)  # raises ValueError if user does not exist

            # check feed exists
            feed = Feed.read(user_hash=self.user_hash, name_hash=self.feed_hash)
            if not feed:
                raise ValueError(f"Feed with hash {self.feed_hash} does not exist")

            item = ItemLoose.read(self.item_url_hash)
            if not item:
                raise ValueError(f"Item with hash {self.item_url_hash} does not exist")

            r.set(self.key, self.json)

    def update(self) -> None:
        self.create()

    def delete(self) -> None:
        with self.db_con() as r:
            r.delete(self.key)

    @classmethod
    def read(cls, user_hash, feed_hash, item_url_hash) -> "ItemState":
        with cls.db_con() as r:
            item_vote_json = r.get(
                f"USER:{user_hash}:FEED:{feed_hash}:ITEM:{item_url_hash}:ITEM_STATE"
            )

        if item_vote_json:
            return cls.model_validate_json(item_vote_json)
        return None

    @classmethod
    def set_state(
        cls,
        user_hash: str,
        feed_hash: str,
        item_url_hash: str,
        score: confloat(ge=-1, le=1) = None,
        score_estimate: confloat(ge=-1, le=1) = None,
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
            # TODO trigger score estimator training

        if score_estimate is not None:
            item_state.score_estimate = score_estimate
            item_state.score_estimate_date = datetime.now()

        if is_read is not None:
            item_state.is_read = is_read

        item_state.update()
