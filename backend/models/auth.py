"""Login request and verification contracts."""

from pydantic import BaseModel, Field

from backend.models.common import InputModel


class LoginRequest(InputModel):
    phone: str


class LoginVerification(LoginRequest):
    code: str = Field(min_length=5, max_length=5)


class LoginChallenge(BaseModel):
    challenge_id: str
    phone: str


class LoginUser(BaseModel):
    phone: str
    display_name: str


class LoginResult(BaseModel):
    user: LoginUser
