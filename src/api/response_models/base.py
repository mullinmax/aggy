from db.base import BlinderBaseModel


class BaseResponseModel(BlinderBaseModel):
    @classmethod
    def from_db_model(cls, db_model):
        raise NotImplementedError
