from datetime import datetime
from pydantic import confloat

from .item import ItemLoose
from .user import User
from .category import Category
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
    user_hash: str
    category_hash: str
    score: confloat(ge=-1, le=1) = None
    score_date: datetime = None
    is_read: bool = None

    @property
    def key(self) -> str:
        return f"USER:{self.user_hash}:CATEGORY:{self.category_hash}:ITEM_VOTE:{self.item_url_hash}"

    def create(self) -> None:
        with self.db_con() as r:
            # check user exists
            User.read(self.user_hash)  # raises ValueError if user does not exist

            # check category exists
            category = Category.read(
                user_hash=self.user_hash, name_hash=self.category_hash
            )
            if not category:
                raise ValueError(
                    f"Category with hash {self.category_hash} does not exist"
                )

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
    def read(cls, user_hash, category_hash, item_url_hash) -> "ItemState":
        with cls.db_con() as r:
            item_vote_json = r.get(
                f"USER:{user_hash}:CATEGORY:{category_hash}:ITEM_VOTE:{item_url_hash}"
            )

        if item_vote_json:
            return cls.model_validate_json(item_vote_json)
        return None

    @classmethod
    def set_state(
        cls,
        user_hash: str,
        category_hash: str,
        item_url_hash: str,
        score: confloat(ge=-1, le=1) = None,
        is_read: bool = None,
    ) -> None:
        item_state = cls.read(user_hash, category_hash, item_url_hash)

        if item_state is None:
            item_state = cls(
                item_url_hash=item_url_hash,
                user_hash=user_hash,
                category_hash=category_hash,
            )

        if score is not None:
            item_state.score = score
            item_state.score_date = datetime.now()

        if is_read is not None:
            item_state.is_read = is_read

        item_state.update()
