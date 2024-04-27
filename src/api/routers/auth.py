from fastapi import APIRouter, Depends, HTTPException, Form
from fastapi.security import OAuth2PasswordBearer

import jwt
from datetime import datetime, timedelta

from shared.db.user import User
from shared.config import config


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

auth_router = APIRouter()


@auth_router.post("/signup")
def create_user(username: str, password: str):
    user = User(name=username)
    if user.exists():
        raise HTTPException(status_code=400, detail="Username already registered")
    user.set_password(password)
    user.create()
    return {"message": "User created"}


@auth_router.post("/login")
def get_token(
    username: str = Form(...), password: str = Form(...), days_to_live: int = 7
):
    try:
        user = User.read(name=username)
    except Exception:
        raise HTTPException(status_code=404, detail="User not found")

    if user.check_password(password=password):
        to_encode = {
            "user": user.name_hash,
            "exp": datetime.utcnow() + timedelta(days=days_to_live),
        }
        token = jwt.encode(
            to_encode, config.get("JWT_SECRET"), algorithm=config.get("JWT_ALGORITHM")
        )
        return {"access_token": token, "token_type": "bearer"}
    raise HTTPException(status_code=401, detail="Incorrect username or password")


def authenticate(token: str = Depends(oauth2_scheme)) -> User:
    try:
        payload = jwt.decode(
            token, config.get("JWT_SECRET"), algorithms=[config.get("JWT_ALGORITHM")]
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

    try:
        user = User.read(name_hash=payload.get("user"))
    except Exception:
        raise HTTPException(status_code=404, detail="User not found")

    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    return user
