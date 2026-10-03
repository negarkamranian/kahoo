"""Login request and verification contracts."""

from pydantic import Field

from backend.models.common import InputModel


class LoginRequest(InputModel):
    phone: str


class LoginVerification(LoginRequest):
    code: str = Field(min_length=5, max_length=5)
