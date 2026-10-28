from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")

    epicwing_env: str = "development"
    database_url: str
    epicwing_secret_key: str = Field(min_length=32)
    epicwing_encryption_key: str
    resend_api_key: str = ""
    mail_from: str = ""
    mail_reply_to: str = ""
    epicwing_sftp_port: int = 2222
    epicwing_allowed_origins: str = (
        "http://127.0.0.1:5183,http://localhost:5183,http://127.0.0.1:5184,http://localhost:5184"
    )

    @property
    def allowed_origins(self) -> list[str]:
        origins = [o.strip() for o in self.epicwing_allowed_origins.split(",") if o.strip()]
        if not self.is_production:
            for origin in (
                "http://127.0.0.1:5183",
                "http://localhost:5183",
                "http://127.0.0.1:5184",
                "http://localhost:5184",
            ):
                if origin not in origins:
                    origins.append(origin)
        return origins

    @property
    def is_production(self) -> bool:
        return self.epicwing_env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
