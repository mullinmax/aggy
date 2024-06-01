from .base import BaseRouteModel

from db.category import Category


class CategoryResponse(BaseRouteModel):
    category_name: str
    category_name_hash: str

    model_config = {
        "json_schema_extra": {
            "example": {
                "category_name": "Technology",
                "category_name_hash": "982d98h98hf1uhfdi1sdhu",
            }
        }
    }

    @classmethod
    def from_db_model(cls, db_model: Category):
        return cls(category_name=db_model.name, category_name_hash=db_model.name_hash)
