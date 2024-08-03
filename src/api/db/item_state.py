from enum import Enum
from datetime import datetime

from .base import BlinderBaseModel


class VoteState(Enum):
    NO_VOTE = 0
    UP_VOTE = 1
    DOWN_VOTE = 2


class VoteReason(Enum):
    NO_REASON = 0
    NOT_RELEVANT = 1
    MISLEADING = 2
    INACCURATE = 3
    BIASED = 4
    CLICKBAIT = 5
    INAPPROPRIATE = 6
    OTHER = 7


class ItemState(BlinderBaseModel):
    item_url_hash: str
    user_id: str
    category_hash: str
    vote: VoteState
    vote_reason: VoteReason
    vote_date: datetime
    read: bool

    @property
    def key(self) -> str:
        return f"USER:{self.user_hash}:CATEGORY:{self.category_hash}:ITEM_VOTE:{self.item_url_hash}"

    def create(self) -> None:
        with self.db_con() as r:
            r.set(self.key, self.model_to_json())

    def update(self) -> None:
        self.create()

    def delete(self) -> None:
        with self.db_con() as r:
            r.delete(self.key)

    @classmethod
    def read(cls, user_hash, category_hash, item_url_hash) -> "ItemState":
        with cls.db_con() as r:
            item_vote_json = r.get(
                f"USER:{user_hash}:CATEGORY:{category_hash}:ITEM_VOTE:{item_url_hash}"
            )

        if item_vote_json:
            return cls.model_validate_json(item_vote_json)
        return None
