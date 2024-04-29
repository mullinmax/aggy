from .base import BaseResponseModel


class AcknowledgeResponse(BaseResponseModel):
    message: str = "Success"

    model_config = {"json_schema_extra": {"example": {"message": "Success"}}}
