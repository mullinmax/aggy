from .base import BaseResponseModel

from shared.db.category import Category


class CategoryResponse(BaseResponseModel):
    name: str
    name_hash: str

    @classmethod
    def from_db_model(cls, db_model: Category):
        return cls(name=db_model.name, name_hash=db_model.name_hash)
