from fastapi import APIRouter
from fastapi.responses import RedirectResponse
import re

from config import config
from route_models.version import Version

admin_router = APIRouter()


# Route to redirect the root to /docs
@admin_router.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/docs", status_code=307)


# route to get the current version of the API
@admin_router.get("/version", response_model=Version)
async def get_version():
    version = config.get("BUILD_VERSION", "0.0.0-beta")

    # clean up the version string
    version = re.search(r"(\d+\.\d+\.\d+)-?beta?", version).group(1)
    return Version(version=version)
