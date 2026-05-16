"""Schemas for the user-facing address endpoints."""
from pydantic import BaseModel, ConfigDict


class AddressOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    label: str
    line1: str
    line2: str | None = None
    city: str
    postal_code: str
    country: str
    is_default: bool
