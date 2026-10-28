import uuid

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    email: str = Field(max_length=320)
    # Obergrenze, damit niemand riesige Eingaben durch Argon2 schicken kann.
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
    new_password: str = Field(min_length=12, max_length=1024)
