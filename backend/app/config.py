import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env")


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("PFT_DATABASE_URL", f"sqlite:///{ROOT_DIR / 'data' / 'finance.db'}")
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
