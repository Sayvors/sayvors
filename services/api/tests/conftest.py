"""Pytest configuration for the Sayvors API test suite.

Uses an in-memory SQLite database with the same SQLAlchemy models, so tests
exercise the real endpoints and aggregation code without a live Postgres or
Kafka. The app lifespan (Kafka/Redis workers) is replaced with a no-op so the
test client starts instantly.
"""
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

# Reply endpoints call the LLM on the real path; mock mode returns canned
# drafts so the workflow is testable without an API key.
os.environ.setdefault("GOOGLE_REVIEWS_MOCK", "true")
# TestClient sends Host: testclient — allow it through TrustedHostMiddleware.
os.environ.setdefault("ALLOWED_HOSTS", '["localhost", "127.0.0.1", "testclient"]')
# Gates the in-code test bypasses (rate limits, LLM calls). Prod code checks
# settings.TESTING — never sys.modules probing — so an import accident in the
# deployed image cannot disarm security controls.
os.environ.setdefault("TESTING", "true")

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.main import app as fastapi_app
from app.modules.users.models import User
from app.modules.channels.models import AutoReplyConfig, Channel
from app.modules.analytics.models import LocationDailyMetric, ReviewInsight
from app.modules.outbox.models import EventOutbox

# In-memory SQLite shared across sessions/threads (StaticPool) so the test
# client and the fixtures read the same rows.
TEST_ENGINE = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    poolclass=StaticPool,
    connect_args={"check_same_thread": False},
    echo=False,
)
TEST_SESSION = async_sessionmaker(TEST_ENGINE, class_=AsyncSession, expire_on_commit=False)


@asynccontextmanager
async def _noop_lifespan(_app):
    yield


# The production lifespan spins up Kafka/Redis workers — skip it in tests.
fastapi_app.lifespan = _noop_lifespan


@pytest_asyncio.fixture
async def engine():
    async with TEST_ENGINE.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with TEST_ENGINE.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db(engine):
    async with TEST_SESSION() as session:
        yield session


@pytest.fixture
def user_id():
    return "test-user-0000-0000-0000-000000000001"


@pytest.fixture
def other_user_id():
    """A second account, for checking rows never leak across users."""
    return "test-user-0000-0000-0000-000000000002"


@pytest_asyncio.fixture
async def channel_id(db, user_id):
    channel = Channel(
        id="test-channel-0000-0000-0000-000000000001",
        user_id=user_id,
        platform="google_reviews",
        platform_user_id="demo-acc-123",
        display_name="Test Burgers",
        status="active",
        metadata_json='{"location_id": "demo-loc-456", "account_id": "demo-acc-123"}',
    )
    db.add(channel)
    await db.commit()
    return channel.id


@pytest_asyncio.fixture
async def config_id(db, channel_id):
    config = AutoReplyConfig(
        id="test-config-0000-0000-0000-000000000001",
        channel_id=channel_id,
        enabled=True,
        tone="friendly",
        min_rating_auto=4,
        model="openai:gpt-4o-mini",
    )
    db.add(config)
    await db.commit()
    return config.id


def _override_get_db():
    async def _dep():
        async with TEST_SESSION() as session:
            yield session

    return _dep


def _override_user(user_id):
    from app.modules.users.models import User as _User

    async def _dep():
        return _User(
            id=user_id,
            email="test@sayvors.com",
            first_name="Test",
            last_name="User",
            password_hash="x",
            onboarded=True,
        )

    return _dep


# The production TrustedHostMiddleware blocks TestClient's host
# ("testclient"). A local .env can override ALLOWED_HOSTS via
# pydantic-settings, so patch the class itself (it is pure ASGI —
# it has no `dispatch`; instances are built lazily from this class).
# NOTE: this must run at module level — the middleware stack is built
# on the first request, after this import-time patch is in place.
try:
    from starlette.middleware.trustedhost import TrustedHostMiddleware

    _orig_trusted_host_init = TrustedHostMiddleware.__init__

    def _permissive_init(self, app, allowed_hosts=None, www_redirect=True):
        _orig_trusted_host_init(self, app, ["*"], www_redirect)

    TrustedHostMiddleware.__init__ = _permissive_init  # noqa: E402
except Exception:
    pass


# Replace production lifespan with a no-op so Kafka/Redis/DB warmup and
# background workers don't interfere with the in-memory test DB.
from contextlib import asynccontextmanager


@asynccontextmanager
async def _noop_lifespan(_app):
    yield


fastapi_app = __import__("app.main", fromlist=["app"]).app

fastapi_app.lifespan = _noop_lifespan  # noqa: E402


@pytest_asyncio.fixture
async def client(user_id, engine):
    from fastapi.testclient import TestClient

    fastapi_app.dependency_overrides.clear()
    fastapi_app.dependency_overrides[__import__("app.core.deps", fromlist=["get_db"]).get_db] = _override_get_db()
    fastapi_app.dependency_overrides[__import__("app.core.deps", fromlist=["get_current_user"]).get_current_user] = _override_user(user_id)

    with TestClient(fastapi_app, raise_server_exceptions=False) as c:
        # CSRF middleware requires a matching cookie + header on mutating requests
        c.cookies.set("csrf_token", "test")
        c.headers["x-csrf-token"] = "test"
        # TrustedHostMiddleware blocks TestClient's host ("testclient").
        # Allow it by patching the middleware instance directly.
        for mw in getattr(fastapi_app, "user_middleware", []):
            allowed_hosts = getattr(mw, "allowed_hosts", None)
            if allowed_hosts is not None:
                if isinstance(allowed_hosts, list):
                    allowed_hosts.extend(["testclient"])
                else:
                    try:
                        mw.allowed_hosts = list(allowed_hosts) + ["testclient"]
                    except Exception:
                        pass
        yield c

    fastapi_app.dependency_overrides.clear()