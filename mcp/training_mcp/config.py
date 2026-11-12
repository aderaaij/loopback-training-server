"""Configuration settings for Training MCP server."""

import sys
from pathlib import Path

from pydantic import Field, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict


# Only exists in a source checkout (mcp/config/.env). Installed as a package —
# as in the Docker image — the path is absent and configuration comes from the
# environment alone.
ENV_FILE = Path(__file__).parent.parent / "config" / ".env"


class Settings(BaseSettings):
    """MCP server configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    training_api_url: str = Field(
        default="http://localhost:8001",
        description="Base URL for Training API",
    )
    training_api_key: SecretStr = Field(
        default=SecretStr(""),
        description="API key for authenticating with Training API",
    )

    require_auth_header: bool = Field(
        default=False,
        description="Require callers to present their own Authorization header (disables the TRAINING_API_KEY fallback)",
    )

    log_level: str = Field(default="INFO", description="Logging level")
    request_timeout: int = Field(default=30, description="HTTP request timeout in seconds")

    def is_configured(self) -> bool:
        """Check if the API key is configured."""
        return bool(self.training_api_key.get_secret_value())


try:
    settings = Settings()
except ValidationError as e:
    print(f"Configuration error: {e}", file=sys.stderr)
    settings = Settings(training_api_key=SecretStr(""))
