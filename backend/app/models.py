from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .crypto import EncryptedString
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
def _now() -> datetime:
    return datetime.now()


class PlaidItem(Base):
    __tablename__ = "plaid_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_id: Mapped[str] = mapped_column(String, unique=True)
    access_token: Mapped[str] = mapped_column(EncryptedString)
    institution_name: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    transactions_cursor: Mapped[str | None] = mapped_column(String, nullable=True)

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
    cost_basis: Mapped[float | None] = mapped_column(Float, nullable=True)
    owner: Mapped[str] = mapped_column(String, default="self")  # contributions stop when the owner retires
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
    guardrails: Mapped[bool] = mapped_column(Boolean, default=False)
    guardrail_band: Mapped[float] = mapped_column(Float, default=0.2)
    guardrail_adjustment: Mapped[float] = mapped_column(Float, default=0.1)
    guardrail_floor: Mapped[float] = mapped_column(Float, default=0.7)
    return_model: Mapped[str] = mapped_column(String, default="allocation")
    stock_return: Mapped[float] = mapped_column(Float, default=0.085)
    bond_return: Mapped[float] = mapped_column(Float, default=0.045)
    stock_volatility: Mapped[float] = mapped_column(Float, default=0.17)
    bond_volatility: Mapped[float] = mapped_column(Float, default=0.06)
    stock_bond_correlation: Mapped[float] = mapped_column(Float, default=0.1)
    stock_allocation_now: Mapped[float] = mapped_column(Float, default=0.9)
    stock_allocation_retired: Mapped[float] = mapped_column(Float, default=0.6)
    cash_return: Mapped[float] = mapped_column(Float, default=0.03)
    tax_mode: Mapped[str] = mapped_column(String, default="progressive")
    filing_status: Mapped[str] = mapped_column(String, default="single")
    effective_tax_rate: Mapped[float] = mapped_column(Float, default=0.15)
    state_tax_rate: Mapped[float] = mapped_column(Float, default=0.0)
    state: Mapped[str] = mapped_column(String, default="")  # two-letter code; "" = flat state_tax_rate
    withdrawal_rate: Mapped[float] = mapped_column(Float, default=0.04)
    ss_monthly_benefit: Mapped[float] = mapped_column(Float, default=0.0)
    ss_claim_age: Mapped[int] = mapped_column(Integer, default=67)
    spouse_birth_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    spouse_ss_monthly_benefit: Mapped[float] = mapped_column(Float, default=0.0)
    spouse_ss_claim_age: Mapped[int] = mapped_column(Integer, default=67)
    spouse_life_expectancy: Mapped[int] = mapped_column(Integer, default=95)
    spouse_retirement_age: Mapped[int | None] = mapped_column(Integer, nullable=True)  # None = same year as you
    survivor_spending: Mapped[float] = mapped_column(Float, default=0.75)
    pre_medicare_cost: Mapped[float] = mapped_column(Float, default=12_000)  # per person per year
    medicare_cost: Mapped[float] = mapped_column(Float, default=7_000)  # per person per year, before IRMAA
    health_cost_growth: Mapped[float] = mapped_column(Float, default=0.02)  # above inflation
    aca_subsidies: Mapped[bool] = mapped_column(Boolean, default=True)
    aca_benchmark_premium: Mapped[float] = mapped_column(Float, default=10_000)  # per person per year
    roth_conversion_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    roth_start_age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    roth_end_age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    cash_flows: Mapped[list["CashFlow"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan", order_by="CashFlow.start_age"
    )
    children: Mapped[list["Child"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan", order_by="Child.birth_year"
    )
    homes: Mapped[list["Home"]] = relationship(back_populates="plan", cascade="all, delete-orphan", order_by="Home.id")


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
    tax_type: Mapped[str] = mapped_column(String, default="wages")
    category: Mapped[str] = mapped_column(String, default="general")
    every_n_years: Mapped[int] = mapped_column(Integer, default=1)
    # "self" | "spouse": ages and "at retirement" follow that person, and the item stops at their death.
    # "joint": ages and retirement follow you; continues for the survivor.
    owner: Mapped[str] = mapped_column(String, default="joint")

    plan: Mapped[Plan] = relationship(back_populates="cash_flows")


class Home(Base):
    """A home owned now or bought later, with its mortgage, carrying costs, and an optional sale.

    A home owned now can be linked to a property account and a mortgage account; their balances
    are then used here instead of counting the accounts separately.
    """

    __tablename__ = "homes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String)
    value: Mapped[float] = mapped_column(Float, default=0.0)  # today's dollars: worth now, or price if bought later
    purchase_age: Mapped[int | None] = mapped_column(Integer, nullable=True)  # None = owned now
    cost_basis: Mapped[float | None] = mapped_column(Float, nullable=True)
    property_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    mortgage_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    mortgage_balance: Mapped[float] = mapped_column(Float, default=0.0)
    mortgage_payment: Mapped[float] = mapped_column(Float, default=0.0)  # monthly
    mortgage_rate: Mapped[float] = mapped_column(Float, default=0.065)
    down_payment: Mapped[float] = mapped_column(Float, default=0.2)
    closing_costs: Mapped[float] = mapped_column(Float, default=0.03)
    mortgage_years: Mapped[int] = mapped_column(Integer, default=30)
    appreciation: Mapped[float] = mapped_column(Float, default=0.0)  # above inflation
    carrying_costs: Mapped[float] = mapped_column(Float, default=0.0)  # share of value per year
    sale_age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    selling_costs: Mapped[float] = mapped_column(Float, default=0.06)

    plan: Mapped[Plan] = relationship(back_populates="homes")


class Child(Base):
    """A child whose yearly cost changes by life stage, ending with optional college years."""

    __tablename__ = "children"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String)
    birth_year: Mapped[int] = mapped_column(Integer)
    cost_early: Mapped[float] = mapped_column(Float, default=18_000)  # ages 0-5, incl. childcare
    cost_middle: Mapped[float] = mapped_column(Float, default=15_000)  # ages 6-12
    cost_teen: Mapped[float] = mapped_column(Float, default=18_000)  # ages 13-17
    college_cost: Mapped[float] = mapped_column(Float, default=30_000)  # per year
    college_start_age: Mapped[int] = mapped_column(Integer, default=18)
    college_years: Mapped[int] = mapped_column(Integer, default=4)

    plan: Mapped[Plan] = relationship(back_populates="children")


class Transaction(Base):
    """A bank or card transaction from Plaid or a CSV import. Positive amounts are money out."""

    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), nullable=True)
    # Plaid's transaction_id, or "csv:<hash>" so re-importing a file does not duplicate rows.
    external_id: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    posted_on: Mapped[date] = mapped_column(Date, index=True)
    description: Mapped[str] = mapped_column(String)
    merchant: Mapped[str | None] = mapped_column(String, nullable=True)
    amount: Mapped[float] = mapped_column(Float)
    category: Mapped[str] = mapped_column(String, default="other")
    category_source: Mapped[str] = mapped_column(String, default="auto")  # "auto" | "rule" | "user"
    plaid_category: Mapped[str | None] = mapped_column(String, nullable=True)
    pending: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    account: Mapped[Account | None] = relationship()


class CategoryRule(Base):
    """Recategorize every transaction from a merchant, now and on future syncs and imports."""

    __tablename__ = "category_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    match: Mapped[str] = mapped_column(String, unique=True)  # normalized merchant or description
    category: Mapped[str] = mapped_column(String)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(String)
