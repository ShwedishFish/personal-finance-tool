from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

ACCOUNT_KINDS = {
    "cash": False,
    "brokerage": False,
    "retirement": False,
    "property": False,
    "other_asset": False,
    "credit_card": True,
    "loan": True,
    "mortgage": True,
    "other_liability": True,
}
TAX_TREATMENTS = ("taxable", "tax_deferred", "tax_free", "none")
CASH_FLOW_KINDS = ("income", "expense", "goal")


def _now() -> datetime:
    return datetime.now()


class PlaidItem(Base):
    __tablename__ = "plaid_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_id: Mapped[str] = mapped_column(String, unique=True)
    access_token: Mapped[str] = mapped_column(String)
    institution_name: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    accounts: Mapped[list["Account"]] = relationship(back_populates="plaid_item")


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    institution: Mapped[str | None] = mapped_column(String, nullable=True)
    kind: Mapped[str] = mapped_column(String)
    tax_treatment: Mapped[str] = mapped_column(String, default="taxable")
    interest_rate: Mapped[float] = mapped_column(Float, default=0.0)
    monthly_payment: Mapped[float] = mapped_column(Float, default=0.0)
    annual_contribution: Mapped[float] = mapped_column(Float, default=0.0)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    plaid_account_id: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    plaid_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("plaid_items.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    plaid_item: Mapped[PlaidItem | None] = relationship(back_populates="accounts")
    balances: Mapped[list["BalanceSnapshot"]] = relationship(
        back_populates="account", cascade="all, delete-orphan", order_by="BalanceSnapshot.as_of"
    )
    holdings: Mapped[list["Holding"]] = relationship(back_populates="account", cascade="all, delete-orphan")

    @property
    def is_liability(self) -> bool:
        return ACCOUNT_KINDS.get(self.kind, False)

    @property
    def latest_balance(self) -> float:
        return self.balances[-1].balance if self.balances else 0.0

    @property
    def latest_as_of(self) -> date | None:
        return self.balances[-1].as_of if self.balances else None


class BalanceSnapshot(Base):
    __tablename__ = "balance_snapshots"
    __table_args__ = (UniqueConstraint("account_id", "as_of"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    as_of: Mapped[date] = mapped_column(Date)
    balance: Mapped[float] = mapped_column(Float)

    account: Mapped[Account] = relationship(back_populates="balances")


class Holding(Base):
    __tablename__ = "holdings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    symbol: Mapped[str | None] = mapped_column(String, nullable=True)
    name: Mapped[str] = mapped_column(String)
    asset_class: Mapped[str] = mapped_column(String, default="other")
    quantity: Mapped[float] = mapped_column(Float, default=0.0)
    value: Mapped[float] = mapped_column(Float, default=0.0)
    as_of: Mapped[date] = mapped_column(Date, default=date.today)

    account: Mapped[Account] = relationship(back_populates="holdings")


class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    birth_year: Mapped[int] = mapped_column(Integer)
    retirement_age: Mapped[int] = mapped_column(Integer, default=65)
    life_expectancy: Mapped[int] = mapped_column(Integer, default=95)
    inflation: Mapped[float] = mapped_column(Float, default=0.025)
    expected_return: Mapped[float] = mapped_column(Float, default=0.07)
    retirement_return: Mapped[float] = mapped_column(Float, default=0.05)
    return_volatility: Mapped[float] = mapped_column(Float, default=0.15)
    cash_return: Mapped[float] = mapped_column(Float, default=0.03)
    effective_tax_rate: Mapped[float] = mapped_column(Float, default=0.15)
    withdrawal_rate: Mapped[float] = mapped_column(Float, default=0.04)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    cash_flows: Mapped[list["CashFlow"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan", order_by="CashFlow.start_age"
    )


class CashFlow(Base):
    __tablename__ = "cash_flows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String)
    amount: Mapped[float] = mapped_column(Float)
    start_age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ends_at_retirement: Mapped[bool] = mapped_column(Boolean, default=False)
    starts_at_retirement: Mapped[bool] = mapped_column(Boolean, default=False)
    real_growth: Mapped[float] = mapped_column(Float, default=0.0)
    taxable: Mapped[bool] = mapped_column(Boolean, default=True)

    plan: Mapped[Plan] = relationship(back_populates="cash_flows")
