"""The AI wallet is workspace-scoped.

The original bug: ``billing/router.py`` and ``rag/agent.py`` charged
``user.id``, so an employee's calls created an ``ai_balance:<employee-id>``
key and spent a wallet nobody could see. Both paths must resolve through
``tenant_id_of(user)`` — the owner's workspace.
"""
from types import SimpleNamespace

import pytest

from app.core.deps import get_current_user
from app.main import app
from app.modules.billing import service as billing_service
from app.modules.billing.schemas import BudgetOut
from app.modules.team.context import tenant_id_of
from app.modules.users.models import User

_HOST = {"host": "localhost"}


def test_tenant_id_of_resolves_an_employee_to_the_owner():
    employee = SimpleNamespace(id="employee-1", tenant_id="owner-1")
    owner = SimpleNamespace(id="owner-1", tenant_id=None)
    assert tenant_id_of(employee) == "owner-1"
    assert tenant_id_of(owner) == "owner-1"


@pytest.mark.asyncio
async def test_budget_endpoint_reads_the_workspace_wallet(client, monkeypatch):
    captured: dict[str, str] = {}

    async def _fake_budget(tenant_id: str, db):
        captured["tenant_id"] = tenant_id
        return BudgetOut(plan="pro", balance_cents=1234, balance_dollars=12.34)

    monkeypatch.setattr(billing_service, "get_budget", _fake_budget)

    async def _employee():
        return User(
            id="employee-1",
            tenant_id="owner-1",
            email="employee@sayvors.test",
            first_name="Emp",
            last_name="Loyee",
            password_hash="x",
            onboarded=True,
        )

    app.dependency_overrides[get_current_user] = _employee
    r = client.get("/api/v1/billing/budget", headers=_HOST)
    assert r.status_code == 200, r.text
    assert captured["tenant_id"] == "owner-1"


@pytest.mark.asyncio
async def test_budget_endpoint_uses_the_owner_id_for_a_sole_account(client, monkeypatch):
    captured: dict[str, str] = {}

    async def _fake_budget(tenant_id: str, db):
        captured["tenant_id"] = tenant_id
        return BudgetOut(plan="free", balance_cents=0, balance_dollars=0.0)

    monkeypatch.setattr(billing_service, "get_budget", _fake_budget)

    r = client.get("/api/v1/billing/budget", headers=_HOST)
    assert r.status_code == 200, r.text
    assert captured["tenant_id"] == "test-user-0000-0000-0000-000000000001"
