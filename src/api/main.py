from fastapi import FastAPI
import uvicorn

from routers.auth import auth_router
from routers.category import category_router
from routers.item import item_router

app = FastAPI()
app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(category_router, prefix="/category", tags=["category"])
app.include_router(item_router, prefix="/item", tags=["item"])


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, log_level="info", reload=True)
