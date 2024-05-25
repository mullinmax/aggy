from .base import BaseRouteModel


class AcknowledgeResponse(BaseRouteModel):
    message: str = "success"

    model_config = {"json_schema_extra": {"example": {"message": "success"}}}
