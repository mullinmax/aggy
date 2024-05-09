from .base import BaseRouteModel


class AuthUser(BaseRouteModel):
    username: str
    password: str

    # prevent password from being printed easily
    def __repr__(self):
        return f"<UserSignup {self.username}>"

    def __str__(self):
        return self.__repr__()

    def __unicode__(self):
        return self.__repr__()

    model_config = {
        "json_schema_extra": {
            "example": {"username": "johndoe", "password": "password"}
        }
    }
