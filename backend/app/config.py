from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")

    forge_env: str = "development"
    database_url: str
    forge_secret_key: str = Field(min_length=32)
    forge_encryption_key: str
    forge_allowed_origins: str = "http://localhost:5173"

    @property
    def allowed_origins(self) -> list[str]:
        return [o.strip() for o in self.forge_allowed_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.forge_env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
