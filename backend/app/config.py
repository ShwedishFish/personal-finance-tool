import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[2]
APP_NAME = "Personal Finance Tool"


def user_data_dir() -> Path:
    """Per-user folder that survives downloading a new copy of the app."""
    if os.getenv("PFT_DATA_DIR"):
        return Path(os.environ["PFT_DATA_DIR"]).expanduser()
    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / APP_NAME
    if os.name == "nt":
        return Path(os.getenv("APPDATA") or home / "AppData" / "Roaming") / APP_NAME
    return Path(os.getenv("XDG_DATA_HOME") or home / ".local" / "share") / "personal-finance-tool"


def default_database_path() -> Path:
    # Installs from before the per-user folder keep their database inside the app folder.
    legacy = ROOT_DIR / "data" / "finance.db"
    return legacy if legacy.exists() else user_data_dir() / "finance.db"


# Settings next to the app win; the per-user copy carries Plaid keys over to a new download.
load_dotenv(ROOT_DIR / ".env")
load_dotenv(user_data_dir() / ".env")


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("PFT_DATABASE_URL", f"sqlite:///{default_database_path()}")
    plaid_client_id: str = os.getenv("PLAID_CLIENT_ID", "")
    plaid_secret: str = os.getenv("PLAID_SECRET", "")
    plaid_env: str = os.getenv("PLAID_ENV", "sandbox").lower()
    plaid_products: list[str] = field(default_factory=lambda: _csv(os.getenv("PLAID_PRODUCTS", "transactions")))
    plaid_optional_products: list[str] = field(
        default_factory=lambda: _csv(os.getenv("PLAID_OPTIONAL_PRODUCTS", "investments,liabilities"))
    )
    plaid_country_codes: list[str] = field(default_factory=lambda: _csv(os.getenv("PLAID_COUNTRY_CODES", "US")))

    @property
    def plaid_enabled(self) -> bool:
        return bool(self.plaid_client_id and self.plaid_secret)


settings = Settings()
