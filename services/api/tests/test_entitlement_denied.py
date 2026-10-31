"""Entitlement denials must be machine-readable for the upgrade prompt.

The dashboard shows a "this feature is premium" modal (instead of a bare
403 toast) whenever a response carries X-Entitlement-Denied. These tests pin
that contract: the header is present on EntitlementDenied, on the shared
helper, and on the value it carries.
"""
import pytest
from fastapi import HTTPException

from app.main import _entitlement_denied_handler
from app.modules.billing.entitlements import (
    ENTITLEMENT_DENIED_HEADER,
    EntitlementDenied,
    entitlement_403,
)


def test_denied_exception_carries_the_feature_key():
    exc = EntitlementDenied("Feature 'leads' is not included in plan 'free'.", feature="leads")
    assert exc.feature == "leads"


def test_denied_exception_defaults_to_no_feature():
    assert EntitlementDenied("nope").feature is None


def test_helper_builds_a_flagged_403():
    err = entitlement_403("Messaging is not included in your plan.", "messaging")
    assert isinstance(err, HTTPException)
    assert err.status_code == 403
    assert err.headers[ENTITLEMENT_DENIED_HEADER] == "messaging"


def test_helper_defaults_to_plan_signal():
    err = entitlement_403("Something plan-related.")
    assert err.headers[ENTITLEMENT_DENIED_HEADER] == "plan"


@pytest.mark.asyncio
async def test_handler_propagates_the_header():
    with pytest.raises(HTTPException) as caught:
        await _entitlement_denied_handler(None, EntitlementDenied("Feature 'voice' is not included.", feature="voice"))
    assert caught.value.status_code == 403
    assert caught.value.headers[ENTITLEMENT_DENIED_HEADER] == "voice"


@pytest.mark.asyncio
async def test_handler_without_feature_still_flags():
    with pytest.raises(HTTPException) as caught:
        await _entitlement_denied_handler(None, EntitlementDenied("Denied."))
    assert caught.value.headers[ENTITLEMENT_DENIED_HEADER] == "plan"
