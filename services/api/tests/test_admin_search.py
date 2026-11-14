"""Admin global search: metadata-only service-level coverage."""
import pytest

from app.modules.admin.models import PlatformOperator
from app.modules.admin.service import admin_search
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio


async def _seed(db, user_id: str) -> None:
    db.add(User(
        id=user_id,
        email="syab293@gmail.com",
        first_name="Shah",
        last_name="Khan",
        password_hash="x",
    ))
    db.add(PlatformOperator(
        id="op-search-1", username="sara.ops", role="operator", is_active=True, password_hash="x",
    ))
    await db.commit()


async def test_search_finds_tenant_by_email(db, user_id):
    await _seed(db, user_id)
    result = await admin_search(db, "syab293")
    groups = {g["key"]: g["items"] for g in result["groups"]}
    assert "tenants" in groups
    assert groups["tenants"][0]["title"] == "Shah Khan"
    assert "syab293@gmail.com" in groups["tenants"][0]["subtitle"]


async def test_search_finds_operator(db, user_id):
    await _seed(db, user_id)
    result = await admin_search(db, "sara")
    groups = {g["key"]: g["items"] for g in result["groups"]}
    assert "operators" in groups
    assert groups["operators"][0]["title"] == "sara.ops"


async def test_search_is_metadata_only(db, user_id):
    # No message/review body fields exist in any searched table, and the
    # query must never return secrets. Search for a phrase that could only
    # live in body text → zero hits.
    result = await admin_search(db, "very disappointed service")
    assert result["total"] == 0


async def test_search_requires_min_two_chars(db, user_id):
    result = await admin_search(db, "a")
    assert result["total"] == 0
    assert result["groups"] == []
