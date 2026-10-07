from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from .finance.tax import BRACKET_RATES

AccountKind = Literal[
    "cash", "brokerage", "retirement", "property", "other_asset", "credit_card", "loan", "mortgage", "other_liability"
]
TaxTreatment = Literal["taxable", "tax_deferred", "tax_free", "none"]
CashFlowKind = Literal["income", "expense", "goal"]
TaxType = Literal["wages", "ordinary", "social_security", "tax_free"]
TaxMode = Literal["progressive", "flat"]
FilingStatus = Literal["single", "married_joint"]


def _check_bracket(rate: float) -> float:
    if not any(abs(rate - r) < 1e-9 for r in BRACKET_RATES[:-1]):
        raise ValueError("must be a federal bracket rate below the top bracket, e.g. 0.22")
    return rate


RothBracket = Annotated[float, AfterValidator(_check_bracket)]
ExpenseCategory = Literal[
    "general", "housing", "home_maintenance", "utilities", "food", "transportation", "healthcare",
    "insurance", "travel", "hobbies", "kids", "education", "giving", "other",
]


class AccountBase(BaseModel):
    name: str = Field(min_length=1)
    institution: str | None = None
    kind: AccountKind
    tax_treatment: TaxTreatment = "taxable"
    interest_rate: float = Field(0.0, ge=0, le=1)
    monthly_payment: float = Field(0.0, ge=0)
    annual_contribution: float = Field(0.0, ge=0)
    cost_basis: float | None = Field(None, ge=0)


class AccountCreate(AccountBase):
    balance: float | None = None
    as_of: date | None = None


class AccountUpdate(BaseModel):
    name: str | None = Field(None, min_length=1)
    institution: str | None = None
    kind: AccountKind | None = None
    tax_treatment: TaxTreatment | None = None
    interest_rate: float | None = Field(None, ge=0, le=1)
    monthly_payment: float | None = Field(None, ge=0)
    annual_contribution: float | None = Field(None, ge=0)
    cost_basis: float | None = Field(None, ge=0)
    archived: bool | None = None


class AccountOut(AccountBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    archived: bool
    is_liability: bool
    latest_balance: float
    latest_as_of: date | None
    linked: bool = False


class BalanceIn(BaseModel):
    balance: float
    as_of: date | None = None


class BalanceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    account_id: int
    as_of: date
    balance: float


class PlanBase(BaseModel):
    name: str = Field(min_length=1)
    birth_year: int = Field(ge=1900, le=2100)
    retirement_age: int = Field(65, ge=18, le=100)
    life_expectancy: int = Field(95, ge=30, le=120)
    inflation: float = Field(0.025, ge=-0.05, le=0.2)
    expected_return: float = Field(0.07, ge=-0.2, le=0.3)
    retirement_return: float = Field(0.05, ge=-0.2, le=0.3)
    return_volatility: float = Field(0.15, ge=0, le=1)
    cash_return: float = Field(0.03, ge=-0.05, le=0.2)
    tax_mode: TaxMode = "progressive"
    filing_status: FilingStatus = "single"
    effective_tax_rate: float = Field(0.15, ge=0, le=0.9)
    state_tax_rate: float = Field(0.0, ge=0, le=0.2)
    withdrawal_rate: float = Field(0.04, gt=0, le=0.2)
    ss_monthly_benefit: float = Field(0.0, ge=0, le=20_000)
    ss_claim_age: int = Field(67, ge=62, le=70)
    spouse_birth_year: int | None = Field(None, ge=1900, le=2100)
    spouse_ss_monthly_benefit: float = Field(0.0, ge=0, le=20_000)
    spouse_ss_claim_age: int = Field(67, ge=62, le=70)
    spouse_life_expectancy: int = Field(95, ge=30, le=120)
    survivor_spending: float = Field(0.75, ge=0.2, le=1)
    pre_medicare_cost: float = Field(12_000, ge=0, le=200_000)
    medicare_cost: float = Field(7_000, ge=0, le=200_000)
    health_cost_growth: float = Field(0.02, ge=-0.05, le=0.1)
    roth_conversion_rate: RothBracket | None = None
    roth_start_age: int | None = Field(None, ge=18, le=100)
    roth_end_age: int | None = Field(None, ge=18, le=100)


class PlanCreate(PlanBase):
    pass


class PlanUpdate(BaseModel):
    name: str | None = Field(None, min_length=1)
    birth_year: int | None = Field(None, ge=1900, le=2100)
    retirement_age: int | None = Field(None, ge=18, le=100)
    life_expectancy: int | None = Field(None, ge=30, le=120)
    inflation: float | None = Field(None, ge=-0.05, le=0.2)
    expected_return: float | None = Field(None, ge=-0.2, le=0.3)
    retirement_return: float | None = Field(None, ge=-0.2, le=0.3)
    return_volatility: float | None = Field(None, ge=0, le=1)
    cash_return: float | None = Field(None, ge=-0.05, le=0.2)
    tax_mode: TaxMode | None = None
    filing_status: FilingStatus | None = None
    effective_tax_rate: float | None = Field(None, ge=0, le=0.9)
    state_tax_rate: float | None = Field(None, ge=0, le=0.2)
    withdrawal_rate: float | None = Field(None, gt=0, le=0.2)
    ss_monthly_benefit: float | None = Field(None, ge=0, le=20_000)
    ss_claim_age: int | None = Field(None, ge=62, le=70)
    spouse_birth_year: int | None = Field(None, ge=1900, le=2100)
    spouse_ss_monthly_benefit: float | None = Field(None, ge=0, le=20_000)
    spouse_ss_claim_age: int | None = Field(None, ge=62, le=70)
    spouse_life_expectancy: int | None = Field(None, ge=30, le=120)
    survivor_spending: float | None = Field(None, ge=0.2, le=1)
    pre_medicare_cost: float | None = Field(None, ge=0, le=200_000)
    medicare_cost: float | None = Field(None, ge=0, le=200_000)
    health_cost_growth: float | None = Field(None, ge=-0.05, le=0.1)
    roth_conversion_rate: RothBracket | None = None
    roth_start_age: int | None = Field(None, ge=18, le=100)
    roth_end_age: int | None = Field(None, ge=18, le=100)


class CashFlowBase(BaseModel):
    name: str = Field(min_length=1)
    kind: CashFlowKind
    amount: float = Field(ge=0)
    start_age: int | None = Field(None, ge=0, le=120)
    end_age: int | None = Field(None, ge=0, le=120)
    ends_at_retirement: bool = False
    starts_at_retirement: bool = False
    real_growth: float = Field(0.0, ge=-0.2, le=0.2)
    tax_type: TaxType = "wages"
    category: ExpenseCategory = "general"
    every_n_years: int = Field(1, ge=1, le=50)


class CashFlowCreate(CashFlowBase):
    pass


class CashFlowUpdate(BaseModel):
    name: str | None = Field(None, min_length=1)
    kind: CashFlowKind | None = None
    amount: float | None = Field(None, ge=0)
    start_age: int | None = Field(None, ge=0, le=120)
    end_age: int | None = Field(None, ge=0, le=120)
    ends_at_retirement: bool | None = None
    starts_at_retirement: bool | None = None
    real_growth: float | None = Field(None, ge=-0.2, le=0.2)
    tax_type: TaxType | None = None
    category: ExpenseCategory | None = None
    every_n_years: int | None = Field(None, ge=1, le=50)


class CashFlowOut(CashFlowBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    plan_id: int


class ChildBase(BaseModel):
    name: str = Field(min_length=1)
    birth_year: int = Field(ge=1900, le=2100)
    cost_early: float = Field(18_000, ge=0)
    cost_middle: float = Field(15_000, ge=0)
    cost_teen: float = Field(18_000, ge=0)
    college_cost: float = Field(30_000, ge=0)
    college_start_age: int = Field(18, ge=14, le=30)
    college_years: int = Field(4, ge=0, le=10)


class ChildCreate(ChildBase):
    pass


class ChildUpdate(BaseModel):
    name: str | None = Field(None, min_length=1)
    birth_year: int | None = Field(None, ge=1900, le=2100)
    cost_early: float | None = Field(None, ge=0)
    cost_middle: float | None = Field(None, ge=0)
    cost_teen: float | None = Field(None, ge=0)
    college_cost: float | None = Field(None, ge=0)
    college_start_age: int | None = Field(None, ge=14, le=30)
    college_years: int | None = Field(None, ge=0, le=10)


class ChildOut(ChildBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    plan_id: int


class PlanOut(PlanBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    cash_flows: list[CashFlowOut] = []
    children: list[ChildOut] = []


class DebtPayoffRequest(BaseModel):
    extra_monthly: float = Field(0.0, ge=0)
    strategy: Literal["avalanche", "snowball"] = "avalanche"
    account_ids: list[int] | None = None
