from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_DATABASE_URL = "postgresql+asyncpg://storymaker:storymaker@localhost:5432/storymaker"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "local"
    database_url: str = DEFAULT_DATABASE_URL

    bot_token: SecretStr
    # Публичный HTTPS-адрес приложения (https://app.<домен>): по нему Telegram
    # открывает Mini App и шлёт вебхук. Без него бот не регистрирует вебхук.
    public_url: str | None = None
    bot_webhook_secret: SecretStr | None = None
    init_data_ttl_seconds: int = 24 * 60 * 60

    sentry_dsn: str | None = None

    # Supabase Storage через S3 API
    s3_endpoint_url: str | None = None
    s3_region: str | None = None
    s3_access_key_id: str | None = None
    s3_secret_access_key: SecretStr | None = None
    s3_bucket_assets: str = "assets"
    s3_bucket_originals: str = "originals"

    @property
    def webhook_url(self) -> str | None:
        if not self.public_url:
            return None
        return self.public_url.rstrip("/") + "/bot/webhook"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # pyright: ignore[reportCallIssue]
