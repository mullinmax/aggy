# app.py
from fastapi import FastAPI
from routers.auth import auth_router
import uvicorn

app = FastAPI()
app.include_router(auth_router, prefix="/auth", tags=["auth"])


@app.get("/")
async def read_root():
    return {"message": "Hello World"}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, log_level="info", reload=True)
