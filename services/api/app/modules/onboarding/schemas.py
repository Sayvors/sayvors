"""Onboarding checklist persistence (DB-backed show/hide + step state)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class OnboardingStateIn(BaseModel):
    dismissed: bool | None = None
    open: bool | None = None
    steps: dict[str, bool] | None = None


class OnboardingStateOut(BaseModel):
    dismissed: bool = False
    open: bool = True
    steps: dict[str, bool] = Field(default_factory=dict)


def _as_bool(value: Any, default: bool) -> bool:
    """Accept real booleans and 0/1 only; anything else keeps the default."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    return default


def normalize_onboarding_state(raw: Any) -> dict:
    if not isinstance(raw, dict):
        raw = {}
    steps = raw.get("steps")
    if not isinstance(steps, dict):
        steps = {}
    return {
        "dismissed": _as_bool(raw.get("dismissed"), False),
        "open": _as_bool(raw.get("open"), True),
        "steps": {str(k): bool(v) for k, v in steps.items()},
    }
