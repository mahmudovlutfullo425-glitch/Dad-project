"""Schemas for authentication endpoints."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=255)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    # Plain str on output: input is already validated as EmailStr at register
    # time, and re-validating on read rejects RFC-special TLDs like .local
    # that the seed data uses (admin@ecom.local).
    email: str
    full_name: str
    is_admin: bool
    created_at: datetime
