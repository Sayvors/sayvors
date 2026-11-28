"""WhatsApp token classification and bounded lifecycle maintenance."""
import asyncio
import logging
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, or_, select, update

from ....config import settings
from .models import MetaConnection
from .providers.base import MetaAPIError, MetaAmbiguousError

logger = logging.getLogger(__name__)


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


def token_health(connection, *, now: datetime | None = None) -> str:
    """Expose only the coarse lifecycle state needed by the Channels UI."""
    if getattr(connection, "provider", None) != "whatsapp":
        return "healthy"
    now = _utc(now or datetime.now(timezone.utc))
    status = getattr(connection, "status", None)
    if status in {"expired", "revoked", "needs_reauth"}:
        return "reauth_required"
    deadlines = [
        _utc(value) for value in (
            getattr(connection, "token_expires_at", None),
            getattr(connection, "data_access_expires_at", None),
        ) if value is not None
    ]
    if deadlines and min(deadlines) <= now:
        return "reauth_required"
    lease = getattr(connection, "token_rotation_lease_until", None)
    if lease is not None and _utc(lease) > now:
        return "rotating"
    if status == "error" or getattr(connection, "token_rotation_error", None):
        return "rotating"
    kind = getattr(connection, "token_kind", None)
    if kind is None:
        return "rotating"
    if kind not in {"USER", "SYSTEM_USER", "BUSINESS_INTEGRATION_SYSTEM_USER"}:
        return "rotating"
    if kind == "USER" and getattr(connection, "token_last_rotated_at", None) is None:
        return "rotating"
    if deadlines and min(deadlines) <= now + ROTATION_LEEWAY:
        return "rotating"
    return "healthy"


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
ROTATION_BATCH_SIZE = 100
ROTATION_CONCURRENCY = 5
ROTATION_LEASE = timedelta(minutes=10)
ROTATION_INTERVAL = timedelta(hours=6)
ROTATION_BACKOFF_BASE = timedelta(minutes=15)
ROTATION_BACKOFF_MAX = ROTATION_INTERVAL


def _due_conditions(now: datetime):
    deadline = case(
        (MetaConnection.token_expires_at.is_not(None)
         & MetaConnection.data_access_expires_at.is_not(None),
         case(
             (MetaConnection.token_expires_at <= MetaConnection.data_access_expires_at,
              MetaConnection.token_expires_at),
             else_=MetaConnection.data_access_expires_at,
         )),
        (MetaConnection.token_expires_at.is_not(None), MetaConnection.token_expires_at),
        else_=MetaConnection.data_access_expires_at,
    )
    horizon = now + ROTATION_LEEWAY
    user = MetaConnection.token_kind == "USER"
    due = or_(
        MetaConnection.token_kind.is_(None),
        user & MetaConnection.token_last_rotated_at.is_(None),
        user & (deadline <= horizon),
        user & deadline.is_(None),
        ~user & (deadline <= horizon),
    )
    return [
        MetaConnection.provider == "whatsapp",
        MetaConnection.status.in_(["active", "error"]),
        MetaConnection.access_token_encrypted.is_not(None),
        or_(MetaConnection.token_rotation_lease_until.is_(None),
            MetaConnection.token_rotation_lease_until <= now),
        or_(MetaConnection.token_rotation_next_attempt_at.is_(None),
            MetaConnection.token_rotation_next_attempt_at <= now),
        due,
    ]


async def select_due_connection_ids(db, *, now: datetime,
                                    limit: int = ROTATION_BATCH_SIZE) -> list[str]:
    rows = (await db.execute(select(MetaConnection.id).where(
        *_due_conditions(_utc(now))
    ).order_by(
        MetaConnection.token_expires_at.asc().nullsfirst(), MetaConnection.id
    ).limit(limit))).scalars().all()
    return list(rows)


async def claim_connection(db, connection_id: str, *, now: datetime):
    """Atomically acquire a short lease; the caller commits before network I/O."""
    now = _utc(now)
    result = await db.execute(update(MetaConnection).where(
        MetaConnection.id == connection_id, *_due_conditions(now),
    ).values(
        token_rotation_lease_until=now + ROTATION_LEASE,
    ).returning(MetaConnection))
    return result.scalar_one_or_none()


def _cas_conditions(claim, expected_ciphertext: str, expected_lease_until: datetime) -> list:
    return [
        MetaConnection.id == claim.id,
        MetaConnection.access_token_encrypted == expected_ciphertext,
        MetaConnection.token_rotation_lease_until == expected_lease_until,
        MetaConnection.status.in_(["active", "error"]),
    ]


async def persist_rotation_success(db, claim, *, token: str, info: TokenInfo,
                                   rotated_at: datetime, expected_ciphertext: str,
                                   expected_lease_until: datetime) -> bool:
    from .credentials import encrypt_credential

    ciphertext = encrypt_credential(token)
    result = await db.execute(update(MetaConnection).where(*_cas_conditions(
        claim, expected_ciphertext, expected_lease_until,
    )).values(
        access_token_encrypted=ciphertext, token_kind=info.token_kind or "USER",
        token_expires_at=info.expires_at, data_access_expires_at=info.data_access_expires_at,
        token_last_rotated_at=rotated_at, token_rotation_attempts=0,
        token_rotation_error=None, token_rotation_next_attempt_at=None,
        token_rotation_lease_until=None, status="active", last_validated_at=rotated_at,
    ).returning(MetaConnection.id))
    if result.scalar_one_or_none() is None:
        return False
    current = await db.get(MetaConnection, claim.id)
    if current is not None:
        metadata = dict(current.connection_metadata or {})
        metadata["token_expiry_source"] = info.expiry_source
        current.connection_metadata = metadata
        db.add(current)
    return True


async def record_transient_failure(db, claim, *, code: str, now: datetime,
                                   expected_ciphertext: str,
                                   expected_lease_until: datetime) -> bool:
    attempts = int(claim.token_rotation_attempts or 0) + 1
    delay = min(ROTATION_BACKOFF_BASE * (2 ** min(attempts - 1, 10)), ROTATION_BACKOFF_MAX)
    safe_code = code if code.replace("_", "").isalnum() and len(code) <= 64 else "rotation_transient"
    result = await db.execute(update(MetaConnection).where(*_cas_conditions(
        claim, expected_ciphertext, expected_lease_until,
    )).values(
        status="error", token_rotation_attempts=attempts,
        token_rotation_error=safe_code,
        token_rotation_next_attempt_at=_utc(now) + delay,
        token_rotation_lease_until=None,
    ).returning(MetaConnection.id))
    return result.scalar_one_or_none() is not None


async def _persist_classification(db, claim, info: TokenInfo, now: datetime,
                                  expected_ciphertext: str,
                                  expected_lease_until: datetime) -> bool:
    result = await db.execute(update(MetaConnection).where(*_cas_conditions(
        claim, expected_ciphertext, expected_lease_until,
    )).values(
        token_kind=info.token_kind, token_expires_at=info.expires_at,
        data_access_expires_at=info.data_access_expires_at,
        token_rotation_attempts=0, token_rotation_error=None,
        token_rotation_next_attempt_at=None, token_rotation_lease_until=None,
        status="active", last_validated_at=now,
    ).returning(MetaConnection.id))
    if result.scalar_one_or_none() is None:
        return False
    current = await db.get(MetaConnection, claim.id)
    if current is not None:
        metadata = dict(current.connection_metadata or {})
        metadata["token_expiry_source"] = info.expiry_source
        current.connection_metadata = metadata
        db.add(current)
    return True


async def _process_connection(connection_id: str, *, session_factory, adapter,
                              now: datetime, semaphore: asyncio.Semaphore) -> bool:
    from .credentials import decrypt_credential

    async with semaphore:
        async with session_factory() as db:
            claim = await claim_connection(db, connection_id, now=now)
            if claim is None:
                await db.rollback()
                return False
            ciphertext = claim.access_token_encrypted
            lease_until = claim.token_rotation_lease_until
            stored = TokenInfo(
                token_kind=claim.token_kind,
                expires_at=_utc(claim.token_expires_at) if claim.token_expires_at else None,
                data_access_expires_at=(
                    _utc(claim.data_access_expires_at)
                    if claim.data_access_expires_at else None
                ),
                scopes=tuple(claim.scopes or []),
            )
            # The claim is committed and the session closed before Meta I/O.
            await db.commit()

        token = decrypt_credential(ciphertext)
        if not token:
            async with session_factory() as db:
                await record_transient_failure(
                    db, claim, code="token_decrypt_failed", now=now,
                    expected_ciphertext=ciphertext, expected_lease_until=lease_until,
                )
                await db.commit()
            return True

        try:
            info = stored
            needs_inspection = info.token_kind is None or info.effective_expires_at is None or (
                classify_token(info) == "validate_only"
                and info.effective_expires_at is not None
                and info.effective_expires_at <= now + ROTATION_LEEWAY
            )
            if needs_inspection:
                info = await adapter.inspect_token(token)
                _confirmed(info)
            action = classify_token(info)
            if action == "reauth":
                raise MetaAPIError("Meta rejected the WhatsApp token", 401)
            should_exchange = (
                action == "exchange_user"
                and (claim.token_last_rotated_at is None or (
                    info.effective_expires_at is not None
                    and info.effective_expires_at <= now + ROTATION_LEEWAY
                ))
            )
            if should_exchange:
                payload = await adapter.exchange_long_lived_token(token)
                rotated = parse_exchange_payload(payload, now=now, allow_user_fallback=True)
                info = TokenInfo(
                    token_kind="USER", expires_at=rotated.expires_at,
                    data_access_expires_at=rotated.data_access_expires_at,
                    is_valid=True, app_id=rotated.app_id, scopes=rotated.scopes,
                    expiry_source=rotated.expiry_source,
                )
                async with session_factory() as db:
                    changed = await persist_rotation_success(
                        db, claim, token=payload["access_token"], info=info,
                        rotated_at=now, expected_ciphertext=ciphertext,
                        expected_lease_until=lease_until,
                    )
                    await db.commit()
                return changed

            if action == "validate_only" and (
                info.effective_expires_at is not None
                and info.effective_expires_at <= now + ROTATION_LEEWAY
            ):
                from .reauth import mark_token_expiring

                async with session_factory() as db:
                    await mark_token_expiring(
                        db, claim, expected_ciphertext=ciphertext,
                        expected_lease_until=lease_until,
                        metadata={
                            "token_kind": info.token_kind,
                            "token_expires_at": info.expires_at,
                            "data_access_expires_at": info.data_access_expires_at,
                            "token_rotation_next_attempt_at": now + timedelta(hours=24),
                        },
                    )
                    await db.commit()
                return True

            async with session_factory() as db:
                changed = await _persist_classification(
                    db, claim, info, now, ciphertext, lease_until,
                )
                await db.commit()
            return changed
        except Exception as exc:
            transient = (
                is_transient_meta_error(exc)
                or isinstance(exc, TokenMetadataError)
                or not isinstance(exc, MetaAPIError)
            )
            code = (
                "invalid_token_metadata" if isinstance(exc, TokenMetadataError)
                else "inspection_transient" if stored.token_kind is None
                else "exchange_transient"
            )
            if not transient:
                code = "rotation_rejected"
            elif not isinstance(exc, (MetaAPIError, MetaAmbiguousError, TokenMetadataError)):
                code = "rotation_internal_error"
            async with session_factory() as db:
                if transient:
                    await record_transient_failure(
                        db, claim, code=code, now=now,
                        expected_ciphertext=ciphertext, expected_lease_until=lease_until,
                    )
                else:
                    from .reauth import mark_needs_reauth

                    await mark_needs_reauth(
                        db, claim, code, expected_ciphertext=ciphertext,
                        expected_lease_until=lease_until,
                    )
                await db.commit()
            logger.warning(
                "WhatsApp token maintenance failed connection=%s code=%s",
                connection_id, code,
            )
            return True


async def run_rotation_pass(*, session_factory=None, adapter=None, now: datetime | None = None,
                            batch_size: int = ROTATION_BATCH_SIZE,
                            concurrency: int = ROTATION_CONCURRENCY) -> int:
    """Process one bounded batch; each connection owns a short committed lease."""
    if session_factory is None:
        from ....database import async_session
        session_factory = async_session
    if adapter is None:
        from .service import get_adapter
        adapter = get_adapter("whatsapp")
    now = _utc(now or datetime.now(timezone.utc))
    batch_size = min(max(int(batch_size), 1), ROTATION_BATCH_SIZE)
    concurrency = min(max(int(concurrency), 1), ROTATION_CONCURRENCY)
    async with session_factory() as db:
        ids = await select_due_connection_ids(db, now=now, limit=batch_size)
    semaphore = asyncio.Semaphore(concurrency)
    results = await asyncio.gather(*(
        _process_connection(
            connection_id, session_factory=session_factory, adapter=adapter,
            now=now, semaphore=semaphore,
        ) for connection_id in ids
    ), return_exceptions=True)
    for result in results:
        if isinstance(result, Exception):
            logger.error("WhatsApp token worker task failed: %s", type(result).__name__)
    return sum(result is True for result in results)


async def run_token_rotation_worker() -> None:
    """Run every six hours with bounded startup jitter."""
    await asyncio.sleep(random.uniform(0, 300))
    while True:
        try:
            processed = await run_rotation_pass()
            logger.info("WhatsApp token rotation pass processed=%d", processed)
        except Exception:
            logger.exception("WhatsApp token rotation pass failed")
        await asyncio.sleep(ROTATION_INTERVAL.total_seconds())


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
        except TokenMetadataError:
            _apply_info(prepared, original)
            prepared.update(
                _token_status="error", token_rotation_error="invalid_token_metadata",
                token_rotation_next_attempt_at=now + timedelta(minutes=15),
            )
            return prepared
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
            rotated = parse_exchange_payload(
                exchanged, now=now, allow_user_fallback=True,
            )
        except TokenMetadataError:
            fallback = info if info.effective_expires_at else original
            _apply_info(prepared, fallback)
            prepared.update(
                _token_status="error", token_rotation_error="invalid_token_metadata",
                token_rotation_next_attempt_at=now + timedelta(minutes=15),
            )
            return prepared
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
