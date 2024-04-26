from fastapi import FastAPI, Depends
import uvicorn

from routers.auth import auth_router, get_current_user
from shared.db.user import User

app = FastAPI()
app.include_router(auth_router, prefix="/auth", tags=["auth"])


@app.get("/")
async def read_root(s: str):
    return {"message": s}


@app.get("/protected")
async def read_protected(s: str, user: User = Depends(get_current_user)):
    return {"message": s}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, log_level="info", reload=True)
