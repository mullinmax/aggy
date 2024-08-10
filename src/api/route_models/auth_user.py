import json

from .base import BaseRouteModel


class AuthUser(BaseRouteModel):
    username: str
    password: str

    # prevent password from being printed easily
    @property
    def as_dict(self):
        return json.loads(self.json)

    @property
    def json(self) -> str:
        js = self.model_dump_json()
        js.pop("password", None)
        return js

    def __str__(self):
        return self.json

    def __repr__(self):
        return self.__str__()

    def __unicode__(self):
        return self.__str__()

    def __bytes__(self):
        return self.__str__().encode("utf-8")

    model_config = {
        "json_schema_extra": {
            "example": {"username": "johndoe", "password": "password"}
        }
    }
