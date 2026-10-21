from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    DATABASE_URL: str = "sqlite+aiosqlite:///./dev.db"
    JWT_SECRET_KEY: str = "dev-only-not-used"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    DEBUG: bool = False
    # Comma-separated browser origins allowed on top of the localhost ones,
    # e.g. "http://<lan-ip>:3001" to open the frontend from another PC on
    # the LAN. Empty (the default) keeps the API localhost-only for CORS.
    CORS_EXTRA_ORIGINS: str = ""


def cors_origins(settings: "Settings") -> list[str]:
    """Localhost dev origins plus any configured CORS_EXTRA_ORIGINS.

    A trailing slash is stripped because browsers send Origin without one and
    Starlette compares the strings exactly. "*" is refused: with
    allow_credentials=True it would let any site on the network drive this
    unauthenticated API from a visitor's browser.
    """
    origins = ["http://localhost:3000", "http://localhost:3001", "http://localhost:3003"]
    for raw in settings.CORS_EXTRA_ORIGINS.split(","):
        origin = raw.strip().rstrip("/")
        if not origin:
            continue
        if origin == "*":
            raise ValueError("CORS_EXTRA_ORIGINS must list explicit origins, not '*'")
        if origin not in origins:
            origins.append(origin)
    return origins


@lru_cache
def get_settings() -> Settings:
    return Settings()
