from pydantic import BaseModel, Field


class TwoFactorStatus(BaseModel):
    enabled: bool
    recovery_codes_remaining: int


class PasswordBody(BaseModel):
    password: str = Field(max_length=1024)


class CodeBody(BaseModel):
    code: str = Field(min_length=6, max_length=32)


class PasswordCodeBody(BaseModel):
    password: str = Field(max_length=1024)
    code: str = Field(min_length=6, max_length=32)


class SetupResponse(BaseModel):
    secret: str
    otpauth_uri: str
    qr_svg: str


class RecoveryCodesResponse(BaseModel):
    recovery_codes: list[str]
