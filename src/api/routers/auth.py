from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from datetime import datetime, timedelta
import jwt

from db.user import User
from config import config
from route_models.token import TokenResponse
from route_models.acknowledge import AcknowledgeResponse
from route_models.auth_user import AuthUser

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/form_login")

auth_router = APIRouter()


@auth_router.post(
    "/signup", summary="Create a user", response_model=AcknowledgeResponse
)
def signup(signup_user: AuthUser) -> AcknowledgeResponse:
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
    try:
        user = User.read(name=form_data.username)
    except Exception:
        raise HTTPException(status_code=404, detail="User not found")

    if user.check_password(password=form_data.password):
        to_encode = {
            "user": user.name_hash,
            "exp": datetime.utcnow() + timedelta(days=7),  # TODO make this configurable
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


@auth_router.get("/get_username", summary="Get username from token", response_model=str)
def get_username(user: User = Depends(authenticate)) -> str:
    return user.name
