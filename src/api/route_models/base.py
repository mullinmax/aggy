from db.base import BlinderBaseModel


class BaseRouteModel(BlinderBaseModel):
    @classmethod
    def from_db_model(cls, db_model):
        raise NotImplementedError
