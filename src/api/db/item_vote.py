from enum import Enum
from datetime import datetime

from .base import BlinderBaseModel


class VoteState(Enum):
    NO_VOTE = 0
    UP_VOTE = 1
    DOWN_VOTE = 2


class ItemMetadata(BlinderBaseModel):
    item_url_hash: str
    user_id: str
    # TODO should this be scoped to a feed/category? that's confusing to the user, but probably good for the models
    vote: VoteState
    vote_date: datetime  # date time or string? or do we even care? (probably nice for ML models)
    read: bool

    @property
    def key(self) -> str:
        return f"USER:{self.user_hash}:ITEM_VOTE:{self.item_url_hash}"

    def create(self) -> None:
        with self.db_con() as r:
            r.set(self.key, self.vote.value)

    def update(self) -> None:
        self.create()

    def delete(self) -> None:
        with self.db_con() as r:
            r.delete(self.key)

    @classmethod
    def read(cls, item_url_hash, user_hash) -> "ItemMetadata":
        with cls.db_con() as r:
            item_vote_json = r.get(f"USER:{user_hash}:ITEM_VOTE:{item_url_hash}")

        if item_vote_json:
            return cls.model_validate_json(item_vote_json)
        return None
