"""WhatsApp token classification and bounded lifecycle maintenance."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from ....config import settings
from .providers.base import MetaAPIError, MetaAmbiguousError


class TokenMetadataError(ValueError):
    """Meta returned malformed token metadata."""


@dataclass(frozen=True)
class TokenInfo:
    token_kind: str | None
    expires_at: datetime | None = None
    data_access_expires_at: datetime | None = None
    is_valid: bool | None = None
    app_id: str | None = None
    scopes: tuple[str, ...] = ()
    expiry_source: str = "unknown"

    @property
    def effective_expires_at(self) -> datetime | None:
        deadlines = [value for value in (self.expires_at, self.data_access_expires_at) if value]
        return min(deadlines) if deadlines else None


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _unix_time(value: object, field: str) -> datetime | None:
    if value is None or value == 0 or value == "":
        return None
    if isinstance(value, bool):
        raise TokenMetadataError(f"invalid {field}")
    try:
        seconds = int(value)
    except (TypeError, ValueError) as exc:
        raise TokenMetadataError(f"invalid {field}") from exc
    if seconds <= 0:
        raise TokenMetadataError(f"invalid {field}")
    return datetime.fromtimestamp(seconds, tz=timezone.utc)


def _token_kind(payload: dict) -> str | None:
    value = payload.get("token_kind") or payload.get("type")
    if value is None:
        return None
    kind = str(value).upper()
    if not kind or len(kind) > 64 or not kind.replace("_", "").isalnum():
        raise TokenMetadataError("invalid token kind")
    return kind


def _relative_expiry(value: object, now: datetime) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise TokenMetadataError("invalid expires_in")
    try:
        seconds = int(value)
    except (TypeError, ValueError) as exc:
        raise TokenMetadataError("invalid expires_in") from exc
    if seconds <= 0:
        raise TokenMetadataError("invalid expires_in")
    return _utc(now) + timedelta(seconds=seconds)


def parse_exchange_payload(payload: dict, *, now: datetime,
                           allow_user_fallback: bool = False) -> TokenInfo:
    """Parse OAuth exchange metadata without interpreting the opaque token."""
    kind = _token_kind(payload)
    expires_at = _relative_expiry(payload.get("expires_in"), now)
    absolute = _unix_time(payload.get("expires_at"), "expires_at")
    if absolute is not None:
        expires_at = min(expires_at, absolute) if expires_at else absolute
    source = "reported" if expires_at else "unknown"
    if expires_at is None and allow_user_fallback and kind == "USER":
        expires_at = _utc(now) + timedelta(days=60)
        source = "user_exchange_fallback_60d"
    return TokenInfo(
        token_kind=kind,
        expires_at=expires_at,
        data_access_expires_at=_unix_time(
            payload.get("data_access_expires_at"), "data_access_expires_at"
        ),
        is_valid=payload.get("is_valid"),
        app_id=str(payload["app_id"]) if payload.get("app_id") else None,
        scopes=tuple(str(scope) for scope in payload.get("scopes", []) or []),
        expiry_source=source,
    )


def parse_debug_token(payload: dict, *, now: datetime) -> TokenInfo:
    """Parse Meta's /debug_token response; ``now`` anchors relative values."""
    data = payload.get("data")
    if not isinstance(data, dict):
        raise TokenMetadataError("missing debug token data")
    return TokenInfo(
        token_kind=_token_kind(data),
        expires_at=_unix_time(data.get("expires_at"), "expires_at"),
        data_access_expires_at=_unix_time(
            data.get("data_access_expires_at"), "data_access_expires_at"
        ),
        is_valid=data.get("is_valid"),
        app_id=str(data["app_id"]) if data.get("app_id") else None,
        scopes=tuple(str(scope) for scope in data.get("scopes", []) or []),
        expiry_source="reported" if data.get("expires_at") else "unknown",
    )


def classify_token(info: TokenInfo) -> str:
    """Return the only lifecycle action supported for this confirmed type."""
    if info.is_valid is False:
        return "reauth"
    if info.token_kind == "USER":
        return "exchange_user"
    if info.token_kind in {"SYSTEM_USER", "BUSINESS_INTEGRATION_SYSTEM_USER"}:
        return "non_expiring" if info.effective_expires_at is None else "validate_only"
    return "validate_only" if info.effective_expires_at else "unknown"


ROTATION_LEEWAY = timedelta(days=7)
TRANSIENT_META_STATUSES = {408, 425, 429}


def is_transient_meta_error(exc: Exception) -> bool:
    if isinstance(exc, MetaAmbiguousError):
        return True
    return isinstance(exc, MetaAPIError) and (
        exc.status_code in TRANSIENT_META_STATUSES or exc.status_code >= 500
    )


def _confirmed(info: TokenInfo) -> None:
    if info.is_valid is False:
        raise MetaAPIError("Meta rejected the WhatsApp token", 401,
                           public="WhatsApp needs reconnection. Please connect again.")
    if info.app_id and settings.META_APP_ID and info.app_id != settings.META_APP_ID:
        raise MetaAPIError("WhatsApp token belongs to another Meta app", 401,
                           public="WhatsApp needs reconnection. Please connect again.")


def _apply_info(credentials: dict, info: TokenInfo) -> None:
    credentials.update(
        token_kind=info.token_kind,
        token_expires_at=info.expires_at,
        data_access_expires_at=info.data_access_expires_at,
        token_expiry_source=info.expiry_source,
        _token_status="active",
        token_rotation_error=None,
    )


async def prepare_whatsapp_credentials(adapter, credentials: dict,
                                       *, now: datetime | None = None) -> dict:
    """Classify a code-exchange token and rotate only confirmed User tokens."""
    now = _utc(now or datetime.now(timezone.utc))
    prepared = dict(credentials)
    token = prepared.get("access_token", "")
    if not token:
        return prepared
    original = parse_exchange_payload(prepared, now=now)
    _confirmed(original)
    info = original
    if info.token_kind is None or classify_token(info) == "unknown":
        try:
            info = await adapter.inspect_token(token)
        except Exception as exc:
            if not is_transient_meta_error(exc):
                raise
            _apply_info(prepared, original)
            prepared.update(
                _token_status="error", token_rotation_error="inspection_transient",
                token_rotation_next_attempt_at=now + timedelta(minutes=15),
            )
            return prepared
        _confirmed(info)

    action = classify_token(info)
    if action == "reauth":
        _confirmed(info)
    if action == "exchange_user":
        try:
            exchanged = await adapter.exchange_long_lived_token(token)
        except Exception as exc:
            if not is_transient_meta_error(exc):
                raise
            fallback = info if info.effective_expires_at else original
            _apply_info(prepared, fallback)
            prepared.update(
                _token_status="error", token_rotation_error="exchange_transient",
                token_rotation_next_attempt_at=now + timedelta(minutes=15),
            )
            return prepared
        rotated = parse_exchange_payload(
            exchanged, now=now, allow_user_fallback=True,
        )
        rotated = TokenInfo(
            token_kind="USER", expires_at=rotated.expires_at,
            data_access_expires_at=rotated.data_access_expires_at,
            is_valid=True, app_id=rotated.app_id, scopes=rotated.scopes,
            expiry_source=rotated.expiry_source,
        )
        prepared.update(exchanged)
        _apply_info(prepared, rotated)
        prepared["token_last_rotated_at"] = now
        return prepared

    _apply_info(prepared, info)
    if action == "unknown":
        prepared.update(_token_status="error", token_rotation_error="token_type_unknown")
    elif action == "validate_only" and info.effective_expires_at <= now + ROTATION_LEEWAY:
        prepared.update(_token_status="error", token_rotation_error="rotation_unsupported")
    return prepared
