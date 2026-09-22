"""Payment-gateway seam (no gateway wired yet).

Card charging/verification will run through the tenant's chosen gateway
(Moyasar / Tap / Stripe) once keys are configured. Until then every
gateway operation fails loudly here — saved cards are unverified
card-on-file records, never charged, and raw PANs/CVCs are never
accepted anywhere (see models.py).
"""
import logging

logger = logging.getLogger(__name__)


def get_payment_provider() -> None:
    """Return the configured gateway client.

    Raises NotImplementedError until an admin wires gateway keys — callers
    must let this propagate (loud misconfiguration, never silent).
    """
    raise NotImplementedError(
        "No payment gateway is configured yet. Cards are saved as "
        "unverified records; live verification lands with the gateway."
    )
