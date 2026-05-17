"""Runtime settings for licitaciones-mcp."""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: str = Field(default="local", alias="LICITACIONES_ENV")
    log_level: str = Field(default="INFO", alias="LICITACIONES_LOG_LEVEL")
    database_url: str = Field(
        default="postgresql+asyncpg://licitaciones:licitaciones@localhost:55432/licitaciones",
        alias="DATABASE_URL",
    )

    mcp_host: str = Field(default="127.0.0.1", alias="LICITACIONES_MCP_HOST")
    mcp_port: int = Field(default=8080, alias="LICITACIONES_MCP_PORT")
    mcp_transport: str = Field(default="streamable-http", alias="LICITACIONES_MCP_TRANSPORT")

    placsp_feed_url: str | None = Field(default=None, alias="PLACSP_FEED_URL")
    placsp_verify_ssl: bool = Field(default=True, alias="PLACSP_VERIFY_SSL")
    ted_api_base_url: str = Field(default="https://api.ted.europa.eu/v3", alias="TED_API_BASE_URL")

    embeddings_provider: Literal["", "openai"] = Field(
        default="", alias="LICITACIONES_EMBEDDINGS_PROVIDER"
    )
    embeddings_model: str = Field(
        default="text-embedding-3-small", alias="LICITACIONES_EMBEDDINGS_MODEL"
    )
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")

    @property
    def embeddings_enabled(self) -> bool:
        """Return whether embeddings can be used for this instance."""

        return self.embeddings_provider == "openai" and bool(self.openai_api_key)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached process settings."""

    return Settings()
