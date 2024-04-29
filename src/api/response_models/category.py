from .base import BaseResponseModel

from shared.db.category import Category


class CategoryResponse(BaseResponseModel):
    name: str
    name_hash: str

    model_config = {
        "json_schema_extra": {
            "example": {"name": "Technology", "name_hash": "982d98h98hf1uhfdi1sdhu"}
        }
    }

    @classmethod
    def from_db_model(cls, db_model: Category):
        return cls(name=db_model.name, name_hash=db_model.name_hash)
