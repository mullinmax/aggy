from db.base import AggyBaseModel


class BaseRouteModel(AggyBaseModel):
    @classmethod
    def from_db_model(cls, db_model):
        raise NotImplementedError
