from .base import BaseRouteModel


class UserInfoResponse(BaseRouteModel):
    username: str

    model_config = {
        "json_schema_extra": {
            "example": {
                "username": "test_user",
            }
        }
    }
