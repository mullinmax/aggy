from fastapi import APIRouter
from fastapi.responses import RedirectResponse

admin_router = APIRouter()


# Route to redirect the root to /docs
@admin_router.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/docs", status_code=307)
