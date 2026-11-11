from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parent.parent / "config" / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str
    # Legacy single-user key, pre-dating per-user tokens. When set, the seed
    # migration registers it as a token owned by the bootstrap admin (so clients
    # from before the auth swap keep working). Fresh installs leave it unset;
    # everyone authenticates with per-user tokens from /api/auth/login.
    api_key: str | None = None
    environment: str = "LOCAL"
    db_host: str | None = None
    # Backup dir mount (docker-compose); the admin System screen reports the
    # newest dump found here. Absent dir = "no backups". When backup_enabled,
    # the server also writes its own dumps here (see app/backup.py): nightly at
    # backup_time (container-local), before pending migrations on startup, and
    # on demand — keeping the newest backup_keep files. Installs that manage
    # backups themselves (host cron into a read-only mount) set
    # BACKUP_ENABLED=false; freshness reporting works either way.
    backup_dir: str = "/backups"
    backup_enabled: bool = True
    backup_time: str = "03:30"
    backup_keep: int = Field(default=30, ge=1)

    @field_validator("backup_time")
    @classmethod
    def _check_backup_time(cls, v: str) -> str:
        hour, _, minute = v.partition(":")
        if not (hour.isdigit() and minute.isdigit() and 0 <= int(hour) <= 23 and 0 <= int(minute) <= 59):
            raise ValueError("BACKUP_TIME must be HH:MM (24h)")
        return v
    # First-run admin bootstrap (see app/cli.py:bootstrap). Password is applied
    # once, only if the admin has none yet; rotating the env var won't reset it.
    bootstrap_admin_username: str = "admin"
    bootstrap_admin_password: str | None = None

    # Route-map tiles, served to the SPA at runtime (GET /api/config) so the
    # published image needs no rebuild to change them. Precedence:
    #   1. MAP_TILE_URL — a full Leaflet URL template ({s} {z} {x} {y} {r} and a
    #      query string are all fine), for any provider;
    #   2. CARTO_API_KEY — the keyed CARTO dark raster URL (CARTO has required a
    #      free key since late 2026; without one it serves a watermark tile);
    #   3. the original keyless CARTO URL, kept so existing installs look the
    #      same until they set one of the above.
    # The key is visible to the browser either way — that is how tile keys work.
    map_tile_url: str | None = None
    map_tile_attribution: str = "&copy; OpenStreetMap &copy; CARTO"
    map_tile_subdomains: str = "abcd"  # only used when the template has {s}
    carto_api_key: str | None = None

    @property
    def map_tiles(self) -> dict[str, str]:
        if self.map_tile_url:
            url = self.map_tile_url
        elif self.carto_api_key:
            url = (
                "https://basemaps.cartocdn.com/rastertiles/dark_all/{z}/{x}/{y}{r}.png"
                f"?key={quote(self.carto_api_key, safe='')}"
            )
        else:
            url = "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
        return {
            "tileUrl": url,
            "attribution": self.map_tile_attribution,
            "subdomains": self.map_tile_subdomains,
        }

    @property
    def db_uri(self) -> str:
        uri = self.database_url
        if self.db_host:
            # Replace hostname in URI for Docker networking
            import re
            uri = re.sub(r"@[^:]+:", f"@{self.db_host}:", uri)
        return uri


@lru_cache()
def get_settings() -> Settings:
    return Settings()
