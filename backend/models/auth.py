"""Persistent guest ownership and explicitly unverified demo login contracts."""

from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from backend.models.common import InputModel


class LoginRequest(InputModel):
    phone: str = Field(pattern=r"^09[0-9]{9}$", min_length=11, max_length=11)


class LoginVerification(LoginRequest):
    challenge_id: str = Field(min_length=36, max_length=36)
    code: str = Field(pattern=r"^[0-9]{5}$", min_length=5, max_length=5)

    @field_validator("challenge_id")
    @classmethod
    def valid_challenge_id(cls, value):
        return str(UUID(value))


class LoginChallenge(BaseModel):
    challenge_id: str
    phone: str


class LoginUser(BaseModel):
    id: int
    phone: str | None
    display_name: str
    phone_verified: bool = False


class LoginResult(BaseModel):
    user: LoginUser


class SessionContext(BaseModel):
    owner_id: int
    session_id: str
    user: LoginUser | None = None


class SessionResult(BaseModel):
    session_id: str
    user: LoginUser | None = None


class LogoutResult(BaseModel):
    logged_out: bool = True
