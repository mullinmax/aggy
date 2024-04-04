from fastapi import APIRouter

auth_router = APIRouter()


@auth_router.post("/token")
async def login_for_access_token():
    return {"token": "fake-token"}


@auth_router.get("/users/me")
async def read_users_me():
    return {"user": "fake-current-user"}
