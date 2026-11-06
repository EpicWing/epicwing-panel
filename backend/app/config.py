from functools import lru_cache
from urllib.parse import urlsplit

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")

    epicwing_env: str = "development"
    database_url: str
    # Database connection pool. Defaults are the same as SQLAlchemy.
    epicwing_db_pool_size: int = Field(default=5, ge=1, le=200)
    epicwing_db_max_overflow: int = Field(default=10, ge=0, le=200)
    # Close connections after this many seconds, so old ones do not break
    epicwing_db_pool_recycle: int = Field(default=1800, ge=60)
    epicwing_secret_key: str = Field(min_length=32)
    epicwing_encryption_key: str
    resend_api_key: str = ""
    mail_from: str = ""
    mail_reply_to: str = ""
    epicwing_sftp_port: int = 2222
    # Public address of the panel, e.g. https://panel.example.com
    epicwing_public_url: str = ""
    # Additional allowed origins, comma-separated (optional)
    epicwing_allowed_origins: str = ""

    @property
    def public_origin(self) -> str:
        parts = urlsplit(self.epicwing_public_url.strip())
        if parts.scheme in ("http", "https") and parts.netloc:
            return f"{parts.scheme}://{parts.netloc}"
        return ""

    @property
    def allowed_origins(self) -> list[str]:
        origins = [
            o.strip().rstrip("/") for o in self.epicwing_allowed_origins.split(",") if o.strip()
        ]
        if self.public_origin and self.public_origin not in origins:
            origins.append(self.public_origin)
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
