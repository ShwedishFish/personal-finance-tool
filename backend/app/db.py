from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from .config import settings


class Base(DeclarativeBase):
    pass


def make_engine(url: str):
    kwargs: dict = {}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        path = url.removeprefix("sqlite:///")
        if url in ("sqlite://", "sqlite:///:memory:"):
            kwargs["poolclass"] = StaticPool
        else:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_conn, _record):
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

    return engine


engine = make_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def apply_update(obj: Base, data: dict) -> None:
    """Set fields from a PATCH body; nulls are only applied to nullable columns."""
    columns = obj.__table__.columns
    for key, value in data.items():
        if value is None and not columns[key].nullable:
            continue
        setattr(obj, key, value)


def _sql_literal(value) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return repr(value)
    return "'" + str(value).replace("'", "''") + "'"


def upgrade_schema(bind) -> None:
    """Bring an existing SQLite database up to the current models.

    New columns are added with their scalar defaults. Renamed or removed columns
    need an explicit data move below.
    """
    with bind.begin() as conn:
        insp = inspect(conn)
        for table in Base.metadata.sorted_tables:
            existing = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in existing:
                    continue
                ddl = f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {col.type.compile(bind.dialect)}'
                if col.default is not None and col.default.is_scalar:
                    ddl += f" DEFAULT {_sql_literal(col.default.arg)}"
                conn.execute(text(ddl))

            if table.name == "cash_flows" and "taxable" in existing:
                conn.execute(text(
                    "UPDATE cash_flows SET tax_type = CASE WHEN taxable THEN 'wages' ELSE 'tax_free' END"
                ))
                conn.execute(text("ALTER TABLE cash_flows DROP COLUMN taxable"))


def init_db(bind=None) -> None:
    from . import models  # noqa: F401  (registers tables)

    bind = bind or engine
    Base.metadata.create_all(bind=bind)
    upgrade_schema(bind)


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session
