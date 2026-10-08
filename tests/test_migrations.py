from sqlalchemy import inspect, text

from app.db import init_db, make_engine


def test_old_database_is_upgraded():
    engine = make_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE plans (id INTEGER PRIMARY KEY, name VARCHAR NOT NULL, birth_year INTEGER NOT NULL, "
            "retirement_age INTEGER NOT NULL, life_expectancy INTEGER NOT NULL, inflation FLOAT NOT NULL, "
            "expected_return FLOAT NOT NULL, retirement_return FLOAT NOT NULL, return_volatility FLOAT NOT NULL, "
            "cash_return FLOAT NOT NULL, effective_tax_rate FLOAT NOT NULL, withdrawal_rate FLOAT NOT NULL, "
            "created_at DATETIME NOT NULL)"
        ))
        conn.execute(text(
            "CREATE TABLE cash_flows (id INTEGER PRIMARY KEY, plan_id INTEGER NOT NULL REFERENCES plans(id), "
            "name VARCHAR NOT NULL, kind VARCHAR NOT NULL, amount FLOAT NOT NULL, start_age INTEGER, end_age INTEGER, "
            "ends_at_retirement BOOLEAN NOT NULL, starts_at_retirement BOOLEAN NOT NULL, real_growth FLOAT NOT NULL, "
            "taxable BOOLEAN NOT NULL)"
        ))
        conn.execute(text(
            "INSERT INTO plans VALUES (1, 'p', 1990, 65, 95, 0.025, 0.07, 0.05, 0.15, 0.03, 0.15, 0.04, '2026-01-01')"
        ))
        conn.execute(text("INSERT INTO cash_flows VALUES (1, 1, 'Gift', 'income', 1, NULL, NULL, 0, 0, 0, 0)"))
        conn.execute(text("INSERT INTO cash_flows VALUES (2, 1, 'Salary', 'income', 1, NULL, NULL, 0, 0, 0, 1)"))

    init_db(engine)

    cols = {c["name"] for c in inspect(engine).get_columns("cash_flows")}
    assert "taxable" not in cols and {"tax_type", "category", "every_n_years"} <= cols
    with engine.connect() as conn:
        tax_types = conn.execute(text("SELECT tax_type FROM cash_flows ORDER BY id")).scalars().all()
        assert tax_types == ["tax_free", "wages"]
        assert conn.execute(text("SELECT tax_mode, ss_claim_age FROM plans")).one() == ("progressive", 67)
    assert inspect(engine).has_table("children")
