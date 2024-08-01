from .base import BaseRouteModel


class Version(BaseRouteModel):
    version: str

    model_config = {"json_schema_extra": {"example": {"version": "1.2.3-beta"}}}
