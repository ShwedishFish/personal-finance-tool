"""Month-by-month debt payoff simulation (avalanche or snowball)."""

from dataclasses import dataclass

MAX_MONTHS = 1200


@dataclass
class Debt:
    name: str
    balance: float
    apr: float
    min_payment: float


def payoff_plan(debts: list[Debt], extra_monthly: float = 0.0, strategy: str = "avalanche") -> dict:
    if strategy not in ("avalanche", "snowball"):
        raise ValueError("strategy must be 'avalanche' or 'snowball'")

    state = [{"debt": d, "balance": d.balance, "interest": 0.0, "paid_off_month": None} for d in debts if d.balance > 0]
    budget = sum(d.min_payment for d in debts) + max(extra_monthly, 0.0)
    timeline = []
    month = 0

    while any(s["balance"] > 0.005 for s in state) and month < MAX_MONTHS:
        month += 1
        for s in state:
            if s["balance"] > 0:
                interest = s["balance"] * s["debt"].apr / 12
                s["balance"] += interest
                s["interest"] += interest

        remaining = budget
        active = [s for s in state if s["balance"] > 0.005]
        for s in active:
            pay = min(s["debt"].min_payment, s["balance"], remaining)
            s["balance"] -= pay
            remaining -= pay

        if strategy == "avalanche":
            active.sort(key=lambda s: (-s["debt"].apr, s["balance"]))
        else:
            active.sort(key=lambda s: (s["balance"], -s["debt"].apr))
        for s in active:
            if remaining <= 0:
                break
            pay = min(s["balance"], remaining)
            s["balance"] -= pay
            remaining -= pay

        for s in state:
            if s["paid_off_month"] is None and s["balance"] <= 0.005:
                s["balance"] = 0.0
                s["paid_off_month"] = month
        timeline.append({"month": month, "total_balance": sum(s["balance"] for s in state)})

    paid_off = all(s["paid_off_month"] is not None for s in state)
    return {
        "strategy": strategy,
        "monthly_budget": budget,
        "paid_off": paid_off,
        "months": month if paid_off else None,
        "total_interest": sum(s["interest"] for s in state),
        "debts": [
            {
                "name": s["debt"].name,
                "starting_balance": s["debt"].balance,
                "apr": s["debt"].apr,
                "interest_paid": s["interest"],
                "paid_off_month": s["paid_off_month"],
            }
            for s in state
        ],
        "timeline": timeline,
    }
