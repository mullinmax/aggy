from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer

import jwt
from datetime import datetime, timedelta

from db.user import User
from config import config
from route_models.token import TokenResponse
from route_models.acknowledge import AcknowledgeResponse
from route_models.auth_user import AuthUser

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

auth_router = APIRouter()


@auth_router.post(
    "/signup", summary="Create a user", response_model=AcknowledgeResponse
)
def create_user(signup_user: AuthUser) -> AcknowledgeResponse:
    user = User(name=signup_user.username)
    if user.exists():
        raise HTTPException(status_code=400, detail="Username already registered")
    user.set_password(signup_user.password)
    user.create()
    return AcknowledgeResponse(acknowledged=True)


@auth_router.post("/login", summary="Get a token", response_model=TokenResponse)
def get_token(auth_user: AuthUser) -> TokenResponse:
    try:
        user = User.read(name=auth_user.username)
    except Exception:
        raise HTTPException(status_code=404, detail="User not found")

    if user.check_password(password=auth_user.password):
        to_encode = {
            "user": user.name_hash,
            "exp": datetime.utcnow() + timedelta(days=7),  # TODO make this configurable
        }
        token = jwt.encode(
            to_encode, config.get("JWT_SECRET"), algorithm=config.get("JWT_ALGORITHM")
        )
        return TokenResponse(token=token, token_type="bearer")
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


@auth_router.get(
    "/token_check", summary="Confirm token is valid", response_model=AcknowledgeResponse
)
def token_check(user: User = Depends(authenticate)) -> AcknowledgeResponse:
    return AcknowledgeResponse(message=user.name)
