from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from datetime import datetime, timedelta, timezone
import jwt

from db.user import User
from config import config
from route_models.token import TokenResponse
from route_models.acknowledge import AcknowledgeResponse
from route_models.auth_user import AuthUser
from route_models.user_info import UserInfoResponse

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/form_login")

auth_router = APIRouter()


@auth_router.post(
    "/signup", summary="Create a user", response_model=AcknowledgeResponse
)
def signup(signup_user: AuthUser) -> AcknowledgeResponse:
    if not config.get_bool("SIGNUP_ENABLED"):
        raise HTTPException(status_code=403, detail="Signups are disabled")

    user = User(name=signup_user.username)
    if user.exists():
        raise HTTPException(status_code=400, detail="Username already registered")
    user.set_password(signup_user.password)
    user.create()
    return AcknowledgeResponse(acknowledged=True)


@auth_router.post(
    "/form_login", summary="Login via OAuth form", response_model=TokenResponse
)
def form_login(form_data: OAuth2PasswordRequestForm = Depends()) -> TokenResponse:
    return login(AuthUser(username=form_data.username, password=form_data.password))


@auth_router.post("/login", summary="Login with AuthUser", response_model=TokenResponse)
def login(form_data: AuthUser) -> TokenResponse:
    # A uniform 401 for unknown users and bad passwords avoids leaking
    # which usernames exist.
    try:
        user = User.read(name=form_data.username)
    except Exception:
        raise HTTPException(status_code=401, detail="Incorrect username or password")

    if user.check_password(password=form_data.password):
        expiration_days = config.get_int("JWT_EXPIRATION_DAYS")
        to_encode = {
            "user": user.name_hash,
            "exp": datetime.now(timezone.utc) + timedelta(days=expiration_days),
        }
        token = jwt.encode(
            to_encode, config.get("JWT_SECRET"), algorithm=config.get("JWT_ALGORITHM")
        )
        return TokenResponse(access_token=token, token_type="bearer")
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


@auth_router.get(
    "/user_info", summary="Get username from token", response_model=UserInfoResponse
)
def get_username(user: User = Depends(authenticate)) -> UserInfoResponse:
    return UserInfoResponse(username=user.name)
