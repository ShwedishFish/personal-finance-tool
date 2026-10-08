import os

from cryptography.fernet import Fernet

os.environ.setdefault("PFT_SECRET_KEY", Fernet.generate_key().decode())  # never touch the real keychain

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.db import get_session, init_db, make_engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture
def session_factory():
    engine = make_engine("sqlite://")
    init_db(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture
def client(session_factory):
    def _session():
        with session_factory() as s:
            yield s

    app.dependency_overrides[get_session] = _session
    yield TestClient(app)
    app.dependency_overrides.clear()
