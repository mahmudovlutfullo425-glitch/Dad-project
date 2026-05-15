"""Authentication endpoints: register, login, current user."""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.deps import get_current_user
from app.models import User
from app.ratelimit.middleware import rate_limit
from app.schemas.auth import Token, UserOut, UserRegister
from app.security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
)
async def register(payload: UserRegister, db: AsyncSession = Depends(get_db)) -> UserOut:
    existing = await db.scalar(select(User).where(User.email == payload.email))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )
    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        full_name=payload.full_name,
        is_admin=False,
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return UserOut.model_validate(user)


@router.post(
    "/login",
    response_model=Token,
    summary="Exchange credentials for a JWT access token",
    # Rate-limit before we even hash the password. Credential
    # stuffing attempts get bounced cheaply at the gateway hop;
    # bcrypt-time is the most expensive thing in this handler.
    dependencies=[Depends(rate_limit("LOGIN_PER_IP"))],
)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
) -> Token:
    # OAuth2PasswordRequestForm names the email field `username` for spec compliance.
    user = await db.scalar(select(User).where(User.email == form_data.username))
    if user is None or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account disabled",
        )

    settings = get_settings()
    token = create_access_token(subject=user.id)
    return Token(access_token=token, expires_in=settings.jwt_expiry_minutes * 60)


@router.get(
    "/me",
    response_model=UserOut,
    summary="Return the authenticated user's profile",
)
async def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(user)
