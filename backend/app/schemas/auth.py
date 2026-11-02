import uuid

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    email: str = Field(max_length=320)
    # Upper limit, so nobody can send huge inputs through Argon2.
    password: str = Field(max_length=1024)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    is_admin: bool


class AuthResponse(BaseModel):
    user: UserOut
    csrf_token: str


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(max_length=1024)
    new_password: str = Field(min_length=8, max_length=1024)


class TwoFactorChallenge(BaseModel):
    two_factor_required: bool = True
    challenge: str


class TwoFactorLoginRequest(BaseModel):
    challenge: str = Field(max_length=512)
    code: str = Field(min_length=6, max_length=32)
