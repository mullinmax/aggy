from .base import BaseRouteModel


class TokenResponse(BaseRouteModel):
    access_token: str
    token_type: str

    model_config = {
        "json_schema_extra": {
            "example": {
                "access_token": "eyJhbGciOicCI6IkpXnBpVUNta3F6elJlZNDgVCJ9.eyJ1c2VyIjoiV0MzEyM30.9B2qIw9KCJKosjaLRwlgWHYLsFTjzW1A005QjJIUzI1NiIsInR5ZZeWg1NkVjWDh6SXRqOFlxVHd5UjlLamFHOCIsImV4cCI6MTcxvqfxeChfZ9s",
                "token_type": "bearer",
            }
        }
    }
