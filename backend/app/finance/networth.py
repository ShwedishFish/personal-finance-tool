from collections import defaultdict
from dataclasses import dataclass
from datetime import date


@dataclass
class Snapshot:
    account_id: int
    as_of: date
    balance: float
    is_liability: bool


def net_worth_history(snapshots: list[Snapshot]) -> list[dict]:
    """Net worth on every date with a snapshot, carrying each account's latest known balance forward."""
    by_date: dict[date, list[Snapshot]] = defaultdict(list)
    for s in snapshots:
        by_date[s.as_of].append(s)

    current: dict[int, Snapshot] = {}
    history = []
    for day in sorted(by_date):
        for s in by_date[day]:
            current[s.account_id] = s
        assets = sum(s.balance for s in current.values() if not s.is_liability)
        liabilities = sum(abs(s.balance) for s in current.values() if s.is_liability)
        history.append(
            {"date": day.isoformat(), "assets": assets, "liabilities": liabilities, "net_worth": assets - liabilities}
        )
    return history


def allocation(items: list[tuple[str, float]]) -> list[dict]:
    totals: dict[str, float] = defaultdict(float)
    for asset_class, value in items:
        if value > 0:
            totals[asset_class] += value
    grand = sum(totals.values())
    return [
        {"asset_class": k, "value": v, "share": v / grand if grand else 0.0}
        for k, v in sorted(totals.items(), key=lambda kv: -kv[1])
    ]
