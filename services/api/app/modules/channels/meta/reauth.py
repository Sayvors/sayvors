"""Conditional WhatsApp reauth transitions and secret-safe alerts."""
import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ....modules.admin.models import AdminNotification
from ....modules.notifications.models import Notification
from ....modules.users.models import User
from .models import MetaConnection

_SAFE_ERROR_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def _safe_code(value: str) -> str:
    return value if _SAFE_ERROR_CODE.fullmatch(value) else "auth_rejected"


def _claim_conditions(connection: MetaConnection, expected_ciphertext: str | None,
                      expected_lease_until: datetime | None) -> list:
    conditions = [
        MetaConnection.id == connection.id,
        MetaConnection.provider == "whatsapp",
        MetaConnection.status.in_(["active", "error", "expired"]),
    ]
    if expected_ciphertext is not None:
        conditions.append(MetaConnection.access_token_encrypted == expected_ciphertext)
    if expected_lease_until is not None:
        conditions.append(MetaConnection.token_rotation_lease_until == expected_lease_until)
    return conditions


async def _alert(db: AsyncSession, connection: MetaConnection, code: str, *, expiring: bool) -> None:
    title = "WhatsApp token expires soon" if expiring else "WhatsApp needs reconnection"
    body = (
        "Automatic rotation is unavailable for this token type. Reconnect before "
        "the reported deadline to avoid an interruption."
        if expiring else
        "WhatsApp rejected the saved credential. Reconnect to resume new sends."
    )
    owner = (await db.execute(select(User).where(User.id == connection.tenant_id))).scalar_one_or_none()
    if owner is not None:
        db.add(Notification(
            id=str(uuid.uuid4()), user_id=owner.id, type="whatsapp_reauth",
            title=title, body=body,
            data={"connection_id": connection.id, "failure_code": code},
            href="/dashboard/channels",
        ))
    db.add(AdminNotification(
        id=str(uuid.uuid4()), kind="system", severity="warning", title=title,
        body=f"Tenant {connection.tenant_id}; connection {connection.id}; code {code}.",
        href="/admin/notifications",
    ))


async def handle_meta_auth_failure(
    db: AsyncSession,
    connection: MetaConnection,
    exc: Exception,
    *,
    expected_ciphertext: str,
) -> bool:
    """Mark the credential used for I/O; a stale rejection cannot win after reconnect."""
    from .providers.base import MetaAPIError

    if not isinstance(exc, MetaAPIError):
        return False
    if exc.status_code in {401, 403}:
        return await mark_needs_reauth(
            db, connection, "send_auth_rejected", expected_ciphertext=expected_ciphertext,
        )
    if exc.status_code != 400:
        return False
    error = exc.payload.get("error", {}) if isinstance(exc.payload, dict) else {}
    auth_codes = {10, 102, 190, 463, 467, 470, 474, 491}
    message = str(exc).lower()
    if error.get("code") in auth_codes or any(text in message for text in (
        "access token", "oauth", "session has expired", "token has expired",
        "invalid token", "token expired",
    )):
        return await mark_needs_reauth(
            db, connection, "send_auth_rejected", expected_ciphertext=expected_ciphertext,
        )
    return False


async def mark_needs_reauth(
    db: AsyncSession,
    connection: MetaConnection,
    failure_code: str = "auth_rejected",
    *,
    expected_ciphertext: str | None = None,
    expected_lease_until: datetime | None = None,
) -> bool:
    """Atomically enter reauth and alert once; False means another state won."""
    code = _safe_code(failure_code)
    conditions = _claim_conditions(connection, expected_ciphertext, expected_lease_until)
    conditions.append(MetaConnection.status != "needs_reauth")
    result = await db.execute(update(MetaConnection).where(*conditions).values(
        status="needs_reauth", token_rotation_error=code,
        token_rotation_lease_until=None, updated_at=datetime.now(timezone.utc),
    ).returning(MetaConnection.id))
    if result.scalar_one_or_none() is None:
        return False
    await _alert(db, connection, code, expiring=False)
    await db.flush()
    await db.refresh(connection)
    return True


async def mark_token_expiring(
    db: AsyncSession,
    connection: MetaConnection,
    failure_code: str = "rotation_unsupported",
    *,
    expected_ciphertext: str | None = None,
    expected_lease_until: datetime | None = None,
    metadata: dict | None = None,
) -> bool:
    """Record an unsupported expiring token and alert once per error episode."""
    code = _safe_code(failure_code)
    conditions = _claim_conditions(connection, expected_ciphertext, expected_lease_until)
    conditions.append(or_(
        MetaConnection.token_rotation_error.is_(None),
        MetaConnection.token_rotation_error != code,
    ))
    values = {
        "status": "error", "token_rotation_error": code,
        "token_rotation_lease_until": None, "updated_at": datetime.now(timezone.utc),
    }
    values.update(metadata or {})
    result = await db.execute(update(MetaConnection).where(*conditions).values(
        **values,
    ).returning(MetaConnection.id))
    if result.scalar_one_or_none() is None:
        return False
    await _alert(db, connection, code, expiring=True)
    await db.flush()
    await db.refresh(connection)
    return True
