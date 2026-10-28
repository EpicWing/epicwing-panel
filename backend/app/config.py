from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")

    epicwing_env: str = "development"
    database_url: str
    epicwing_secret_key: str = Field(min_length=32)
    epicwing_encryption_key: str
    epicwing_allowed_origins: str = "http://localhost:5173"

    @property
    def allowed_origins(self) -> list[str]:
        return [o.strip() for o in self.epicwing_allowed_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.epicwing_env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
