from datetime import datetime
from typing import Optional

from .db.item_loose import ItemLoose
from .base import BlinderBaseModel

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
    score: Optional[float] = None
    score_date: Optional[datetime] = None
    is_read: bool = None

    @property
    def key(self) -> str:
        return f"USER:{self.user_hash}:CATEGORY:{self.category_hash}:ITEM_VOTE:{self.item_url_hash}"

    def create(self) -> None:
        with self.db_con() as r:
            # check item exists
            item = ItemLoose.read(self.item_url_hash)
            if not item:
                raise ValueError(
                    f"Item with url_hash {self.item_url_hash} does not exist"
                )

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

    @classmethod
    def set_score(
        cls, user_hash, category_hash, item_url_hash, score, mark_as_read
    ) -> None:
        item_state = cls.read(user_hash, category_hash, item_url_hash)

        item_state.score = score
        item_state.is_read = mark_as_read
        item_state.score_date = datetime.now()

        item_state.update()
