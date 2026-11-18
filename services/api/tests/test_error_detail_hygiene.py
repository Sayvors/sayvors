"""LAUNCH-S10 guardrail: internal error text must not reach HTTP clients.

Phase 1 removed raw provider text from 502 paths and the Meta error split did
the same for connect endpoints. This test pins the invariant so a future
endpoint cannot quietly reintroduce it. It inspects source rather than hitting
every route, which would miss the rare failure paths that matter here.

Curated domain messages (ValueError, RequestError, CampaignError, ...) are
allowed: "Choose a plan" is a good client error. What is forbidden is a raw
exception from an unknown/provider/general branch, or any 5xx detail built
from str(exception).
"""
import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"

SAFE_EXCEPTIONS = {
    "ValueError", "TypeError", "RequestError", "CampaignError",
    "RecipientError", "AssignmentError", "FeedbackCooldownError",
    "NotImplementedError",
}


def _exception_names(handler: ast.ExceptHandler) -> set[str]:
    if handler.type is None:
        return {"Exception"}
    if isinstance(handler.type, ast.Name):
        return {handler.type.id}
    if isinstance(handler.type, ast.Tuple):
        return {e.id for e in handler.type.elts if isinstance(e, ast.Name)}
    if isinstance(handler.type, ast.Attribute):
        return {handler.type.attr}
    return {"Exception"}


def _is_build_from_exception(value: ast.AST, names: set[str]) -> bool:
    for node in ast.walk(value):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "str":
            if node.args and isinstance(node.args[0], ast.Name) and node.args[0].id in names:
                return True
    return False


def _find_violations() -> list[str]:
    violations: list[str] = []
    for path in sorted(APP.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for handler in [n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler)]:
            bound = {handler.name} if handler.name else set()
            raised = _exception_names(handler)
            if bound and SAFE_EXCEPTIONS.intersection(raised) and not raised - SAFE_EXCEPTIONS:
                continue  # curated domain error: safe by design
            for call in [n for n in ast.walk(handler) if isinstance(n, ast.Call)]:
                func = call.func
                if not (isinstance(func, ast.Attribute) and func.attr == "HTTPException"):
                    continue
                status = None
                for kw in call.keywords:
                    if kw.arg == "status_code" and isinstance(kw.value, ast.Constant):
                        status = kw.value.value
                    if kw.arg == "detail" and _is_build_from_exception(kw.value, bound):
                        if status is None or (isinstance(status, int) and status >= 500):
                            violations.append(
                                f"{path.relative_to(APP)}:{call.lineno} "
                                f"raises {status or 'dynamic-status'} with str({handler.name}) "
                                f"from {sorted(raised)}"
                            )
    return violations


def test_no_raw_exception_text_in_error_details():
    violations = _find_violations()
    assert not violations, "Internal error text may reach clients:\n" + "\n".join(violations)


def test_email_failure_does_not_name_internal_config(client, monkeypatch):
    """The email service's RuntimeError names RESEND_API_KEY; clients see none of it."""
    import app.modules.email.router as email_router

    async def _allow(*args, **kwargs):
        return True

    async def _boom(*args, **kwargs):
        raise RuntimeError("Server is missing RESEND_API_KEY in .env.")

    monkeypatch.setattr(email_router, "rate_limit", _allow)
    monkeypatch.setattr(
        "app.modules.email.service.send_otp_email", _boom
    )
    response = client.post("/api/v1/email/otp/request", json={"email": "someone@example.com"})
    assert response.status_code == 503
    assert "RESEND_API_KEY" not in response.text
    assert "temporarily unavailable" in response.text
