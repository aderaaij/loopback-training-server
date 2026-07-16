"""Test harness: an isolated Postgres database + two authenticated users.

Runs inside the backend container against the compose `db`. Creates a throwaway
`training_api_test` database, builds the schema from the models (create_all),
overrides the request DB session, and mints real tokens for two users so tests
exercise the true auth + scoping path via TestClient.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import app.auth as auth_module
from app.config import get_settings
from app.database import Base, _get_db
from app.main import app
from app.models.api_token import ApiToken
from app.models.user import User
from app.security import generate_token, hash_password, hash_token

TEST_DB_NAME = "training_api_test"


def _swap_db(uri: str, name: str) -> str:
    return uri.rsplit("/", 1)[0] + "/" + name


@pytest.fixture(scope="session")
def engine():
    base_uri = get_settings().db_uri
    maint = create_engine(_swap_db(base_uri, "postgres"), isolation_level="AUTOCOMMIT")
    with maint.connect() as c:
        c.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB_NAME} WITH (FORCE)"))
        c.execute(text(f"CREATE DATABASE {TEST_DB_NAME}"))
    maint.dispose()

    eng = create_engine(_swap_db(base_uri, TEST_DB_NAME))
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def session_factory(engine):
    return sessionmaker(bind=engine)


@pytest.fixture(autouse=True)
def wire(engine, session_factory, monkeypatch):
    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[_get_db] = override_get_db
    # _touch_last_used opens its own session — point it at the test DB too.
    monkeypatch.setattr(auth_module, "SessionLocal", session_factory)
    # All TestClient requests share one client IP, so the login rate limit
    # (5/min) bleeds across tests unless cleared.
    app.state.limiter.reset()

    with engine.begin() as c:
        for table in reversed(Base.metadata.sorted_tables):
            c.execute(text(f'DELETE FROM "{table.name}"'))

    yield
    app.dependency_overrides.clear()


def _make_user(session_factory, username: str, role: str = "user") -> tuple[uuid.UUID, str]:
    with session_factory() as db:
        user = User(username=username, role=role, display_name=username, password_hash=hash_password("pw"))
        db.add(user)
        db.commit()
        db.refresh(user)
        raw = generate_token()
        db.add(ApiToken(user_id=user.id, token_hash=hash_token(raw), name="test-device"))
        db.commit()
        return user.id, raw


def _client(token: str) -> TestClient:
    c = TestClient(app)
    c.headers["Authorization"] = f"Bearer {token}"
    return c


@pytest.fixture()
def user_a(session_factory):
    return _make_user(session_factory, "alice")


@pytest.fixture()
def user_b(session_factory):
    return _make_user(session_factory, "bob")


@pytest.fixture()
def admin_user(session_factory):
    return _make_user(session_factory, "root", role="admin")


@pytest.fixture()
def client_admin(admin_user):
    return _client(admin_user[1])


@pytest.fixture()
def client_a(user_a):
    return _client(user_a[1])


@pytest.fixture()
def client_b(user_b):
    return _client(user_b[1])
