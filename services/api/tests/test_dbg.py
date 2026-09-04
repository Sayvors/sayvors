import pytest


@pytest.mark.asyncio
async def test_dbg(client):
    from app.config import settings

    print("ALLOWED_HOSTS =", settings.ALLOWED_HOSTS)
    r = client.get("/api/v1/analytics/overview?days=30")
    print("STATUS", r.status_code, "BODY", r.text[:800])