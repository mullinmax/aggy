from enum import Enum
from datetime import datetime

from .base import BlinderBaseModel


class VoteState(Enum):
    NO_VOTE = 0
    UP_VOTE = 1
    DOWN_VOTE = 2


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


class ItemState(BlinderBaseModel):
    item_url_hash: str
    user_id: str
    category_hash: str
    vote: VoteState
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
