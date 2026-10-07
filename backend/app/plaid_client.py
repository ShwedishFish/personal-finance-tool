"""Thin wrapper around the Plaid SDK that returns plain dicts."""

import json

import plaid
from plaid.api import plaid_api
from plaid.model.accounts_get_request import AccountsGetRequest
from plaid.model.country_code import CountryCode
from plaid.model.investments_holdings_get_request import InvestmentsHoldingsGetRequest
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.item_remove_request import ItemRemoveRequest
from plaid.model.liabilities_get_request import LiabilitiesGetRequest
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.products import Products

from .config import Settings

SKIPPABLE_ERRORS = {
    "PRODUCTS_NOT_SUPPORTED",
    "PRODUCT_NOT_READY",
    "NO_INVESTMENT_ACCOUNTS",
    "NO_LIABILITY_ACCOUNTS",
    "ADDITIONAL_CONSENT_REQUIRED",
    "INVALID_PRODUCT",
}


class PlaidError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def _wrap(exc: plaid.ApiException) -> PlaidError:
    try:
        body = json.loads(exc.body)
        return PlaidError(body.get("error_code", "UNKNOWN"), body.get("error_message", str(exc)))
    except (TypeError, ValueError):
        return PlaidError("UNKNOWN", str(exc))


class PlaidGateway:
    def __init__(self, settings: Settings):
        host = plaid.Environment.Production if settings.plaid_env == "production" else plaid.Environment.Sandbox
        config = plaid.Configuration(
            host=host, api_key={"clientId": settings.plaid_client_id, "secret": settings.plaid_secret}
        )
        self._client = plaid_api.PlaidApi(plaid.ApiClient(config))
        self._settings = settings

    def create_link_token(self) -> str:
        s = self._settings
        request = LinkTokenCreateRequest(
            user=LinkTokenCreateRequestUser(client_user_id="local-user"),
            client_name="Personal Finance Tool",
            products=[Products(p) for p in s.plaid_products],
            optional_products=[Products(p) for p in s.plaid_optional_products],
            country_codes=[CountryCode(c) for c in s.plaid_country_codes],
            language="en",
        )
        try:
            return self._client.link_token_create(request).to_dict()["link_token"]
        except plaid.ApiException as exc:
            raise _wrap(exc) from exc

    def exchange_public_token(self, public_token: str) -> tuple[str, str]:
        try:
            resp = self._client.item_public_token_exchange(
                ItemPublicTokenExchangeRequest(public_token=public_token)
            ).to_dict()
        except plaid.ApiException as exc:
            raise _wrap(exc) from exc
        return resp["access_token"], resp["item_id"]

    def get_accounts(self, access_token: str) -> list[dict]:
        try:
            return self._client.accounts_get(AccountsGetRequest(access_token=access_token)).to_dict()["accounts"]
        except plaid.ApiException as exc:
            raise _wrap(exc) from exc

    def get_holdings(self, access_token: str) -> dict | None:
        try:
            return self._client.investments_holdings_get(
                InvestmentsHoldingsGetRequest(access_token=access_token)
            ).to_dict()
        except plaid.ApiException as exc:
            err = _wrap(exc)
            if err.code in SKIPPABLE_ERRORS:
                return None
            raise err from exc

    def get_liabilities(self, access_token: str) -> dict | None:
        try:
            return self._client.liabilities_get(LiabilitiesGetRequest(access_token=access_token)).to_dict()[
                "liabilities"
            ]
        except plaid.ApiException as exc:
            err = _wrap(exc)
            if err.code in SKIPPABLE_ERRORS:
                return None
            raise err from exc

    def remove_item(self, access_token: str) -> None:
        try:
            self._client.item_remove(ItemRemoveRequest(access_token=access_token))
        except plaid.ApiException as exc:
            raise _wrap(exc) from exc
