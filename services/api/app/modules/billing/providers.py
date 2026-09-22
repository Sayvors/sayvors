"""Payment-gateway seam.

A local **stub** gateway is wired for development: it tokenizes card
metadata (never a PAN/CVC — those never reach this server) and returns
always-succeed charge receipts so the billing UI and API flow can be
exercised end-to-end before Moyasar/Tap/Stripe keys exist.

Real gateway ids (moyasar, tap, stripe, ...) still raise loudly until
an admin configures their keys — the stub must never silently stand in
for a live processor in production.
"""
import logging
import uuid

logger = logging.getLogger(__name__)

STUB_PROVIDER = "stub"
_STUB_TOKEN_PREFIX = "pm_stub_"
_STUB_CHARGE_PREFIX = "ch_stub_"


class StubPaymentGateway:
    """Dev-only stand-in shaped like Moyasar/Tap/Stripe. No network I/O."""

    name = STUB_PROVIDER

    def tokenize(
        self,
        *,
        brand: str,
        last4: str,
        exp_month: int,
        exp_year: int,
        holder_name: str | None = None,
    ) -> dict:
        return {
            "token": f"{_STUB_TOKEN_PREFIX}{uuid.uuid4().hex}",
            "provider": self.name,
            "brand": brand,
            "last4": last4,
            "exp_month": exp_month,
            "exp_year": exp_year,
            "holder_name": holder_name,
        }

    def verify_token(self, token: str) -> dict:
        if not isinstance(token, str) or not token.startswith(_STUB_TOKEN_PREFIX):
            raise ValueError("Invalid stub gateway token.")
        return {"token": token, "provider": self.name, "verified": True}

    def charge(
        self,
        *,
        token: str,
        amount_cents: int,
        currency: str = "usd",
        description: str | None = None,
    ) -> dict:
        self.verify_token(token)
        if amount_cents <= 0:
            raise ValueError("Charge amount must be positive.")
        return {
            "id": f"{_STUB_CHARGE_PREFIX}{uuid.uuid4().hex}",
            "provider": self.name,
            "status": "succeeded",
            "amount_cents": amount_cents,
            "currency": currency,
            "description": description,
        }


def get_payment_provider(name: str = STUB_PROVIDER) -> StubPaymentGateway:
    """Return the gateway client for `name`.

    The stub is always available for local/dev wiring. Any real gateway
    id raises NotImplementedError until its keys are configured — callers
    must let this propagate (loud misconfiguration, never silent).
    """
    if name == STUB_PROVIDER:
        return StubPaymentGateway()
    raise NotImplementedError(
        f"No payment gateway '{name}' is configured yet. Use "
        f"provider='{STUB_PROVIDER}' for the local stub, or wire real "
        "gateway keys first."
    )
