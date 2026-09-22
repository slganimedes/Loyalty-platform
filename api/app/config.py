"""Application configuration, loaded from environment / .env."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env", extra="ignore"
    )

    # Core
    database_url: str = "sqlite:///./loyalty.db"
    public_api_url: str = "https://api.example.com"
    public_admin_url: str = "https://admin.example.com"

    pass_asset_max_bytes: int = 4 * 1024 * 1024
    pass_asset_max_pixels: int = 4096 * 4096

    # Security
    auth_enabled: bool = False  # Requested public test mode; enable for tenant-protected use.
    pan_hash_secret: str = "change-me-in-env"
    session_hours: int = 12
    bootstrap_admin_username: str = "admin"
    bootstrap_admin_password: str = ""
    assets_dir: str = "/data/assets"

    # Apple Wallet (placeholders — real values via .env / Unraid appdata)
    apple_team_id: str = ""
    apple_pass_type_id: str = "pass.org.slmartinez.loyalty"
    apple_cert_path: str = "/certs/pass.p12"
    apple_cert_password: str = ""
    apple_wwdr_cert_path: str = "/certs/wwdr.pem"
    apple_webservice_url: str = "https://api.example.com"

    # Google Wallet
    google_issuer_id: str = ""
    google_sa_json: str = "/certs/google-sa.json"


settings = Settings()
