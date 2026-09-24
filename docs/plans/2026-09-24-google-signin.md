# Google Sign-In Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users sign up, sign in, and link existing password accounts via Google Identity Services, storing identity (`google_sub`, avatar, profile snapshot) only in Sayvors' DB.

**Architecture:** Frontend loads Google's GIS script and renders the official button on the existing `AuthForm`; the credential (ID token) is POSTed to a new `POST /api/v1/auth/google/verify`, which verifies signature/audience/expiry, find-or-creates the user, and issues a session byte-for-byte identical to password login (access token in JSON + refresh token via `_set_session_cookies`).

**Tech Stack:** FastAPI + SQLAlchemy async, Alembic, `google-auth` (already installed via `google-genai`), Next.js client components, Google Identity Services (`accounts.google.com/gsi/client`), pytest + `asyncio_mode=auto`.

**Spec:** `docs/specs/2026-09-24-google-signin-design.md`

**Repo ground rules (from session):** Windows/PowerShell (no `&&`; use `; if ($?)`), venv python `D:\code\sayvors\.venv\Scripts\python.exe`, pytest from `services/api`, tsc from `apps/web`, never co-author commits, never push unless the user says "push", 4 known pre-existing test failures (`test_admin_health_structure`, `test_overview_empty`, `test_autoreply_model_restricted_to_admin_enabled`, `test_period_bounds_equal_length`) are NOT regressions.

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `services/api/alembic/versions/c6d7e8f9a0b1_users_google_identity.py` | Add `users.google_sub` (unique) + `users.avatar_url` |
| Modify | `services/api/app/modules/users/models.py` | The two new columns |
| Modify | `services/api/app/security.py` | `verify_google_id_token()` — signature/aud/exp/email checks |
| Modify | `services/api/app/modules/auth/events.py` | Optional `metadata` on `log_signup`/`log_login` |
| Modify | `services/api/app/modules/auth/service.py` | `google_login()` find-or-create + `_issue_session()` |
| Modify | `services/api/app/modules/auth/schemas.py` | `GoogleVerifyRequest` |
| Modify | `services/api/app/modules/auth/router.py` | `POST /api/v1/auth/google/verify` |
| Create | `services/api/tests/test_google_signin.py` | All backend tests |
| Modify | `apps/web/lib/auth-context.tsx` | `googleLogin(idToken)` |
| Modify | `apps/web/components/AuthForm.tsx` | Replace stub Google button with GIS render |
| Modify | `apps/web/.env.example` | `NEXT_PUBLIC_GOOGLE_CLIENT_ID` |

**Existing code this leans on (do not duplicate):**
- `_set_session_cookies(response, refresh_token)` — `auth/router.py:54`
- Login response shape — `{access_token, user{id, first_name, last_name, email, email_verified, onboarded}}` with refresh popped into cookie (`auth/router.py:186-188`)
- Session issuance pattern — `login()` in `auth/service.py` (tokens, `RefreshToken` row w/ fingerprint, `store_session`, `log_login`)
- Rate-limit pattern — `rate_limit(f"...:{ip}", n, 60)`; tests patch `app.modules.auth.router.rate_limit`
- Test fixtures — `client`, `db`, `user_id`, `engine` from `tests/conftest.py`; style per `tests/test_password_reset.py`
- AuthForm Google stub to replace — `apps/web/components/AuthForm.tsx:325-329`

---

### Task 1: Migration + model columns

**Files:**
- Modify: `services/api/app/modules/users/models.py`
- Create: `services/api/alembic/versions/c6d7e8f9a0b1_users_google_identity.py`

- [ ] **Step 1: Add columns to the model**

In `services/api/app/modules/users/models.py`, after the `theme`/`language`
columns (around line 34), add:

```python
    # Google identity (sign-in with Google). Non-NULL google_sub ⇒ the account
    # authenticates via Google; password_hash stays a random unusable value.
    google_sub: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True, index=True)
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
```

- [ ] **Step 2: Create the migration**

Create `services/api/alembic/versions/c6d7e8f9a0b1_users_google_identity.py`:

```python
"""users: google_sub (unique) + avatar_url

Revision ID: c6d7e8f9a0b1
Revises: b5c6d7e8f9a0
Create Date: 2026-09-24
"""
from alembic import op
import sqlalchemy as sa

revision = "c6d7e8f9a0b1"
down_revision = "b5c6d7e8f9a0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("google_sub", sa.String(length=64), nullable=True))
    op.add_column("users", sa.Column("avatar_url", sa.String(length=500), nullable=True))
    op.create_index(op.f("ix_users_google_sub"), "users", ["google_sub"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_users_google_sub"), table_name="users")
    op.drop_column("users", "avatar_url")
    op.drop_column("users", "google_sub")
```

- [ ] **Step 3: Apply, verify, round-trip**

Run (from `services/api`):

```powershell
& "D:\code\sayvors\.venv\Scripts\python.exe" -m alembic upgrade head
```

Expected: no error; `alembic current` shows `c6d7e8f9a0b1`.

```powershell
& "D:\code\sayvors\.venv\Scripts\python.exe" -m alembic downgrade -1; if ($?) { & "D:\code\sayvors\.venv\Scripts\python.exe" -m alembic upgrade head }
```

Expected: down then up both succeed; heads still single: `b5c6d7e8f9a0` is no longer head — new head is `c6d7e8f9a0b1`.

- [ ] **Step 4: Commit**

```powershell
git add services/api/app/modules/users/models.py services/api/alembic/versions/c6d7e8f9a0b1_users_google_identity.py
git commit -m "feat(users): google_sub + avatar_url columns for Google sign-in"
```

---

### Task 2: `verify_google_id_token` (TDD)

**Files:**
- Modify: `services/api/app/security.py`
- Create: `services/api/tests/test_google_signin.py`

- [ ] **Step 1: Write the failing tests**

Create `services/api/tests/test_google_signin.py`:

```python
"""Google sign-in: token verification, find-or-create service, verify endpoint."""
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from app.security import verify_google_id_token
from app.modules.users.models import User

GOOD_CLAIMS = {
    "sub": "google-sub-001",
    "email": "guser@sayvors.com",
    "email_verified": True,
    "name": "G User",
    "picture": "https://img.example/p.png",
}


def test_verify_accepts_good_claims():
    with patch(
        "app.security.verify_oauth2_token", return_value=dict(GOOD_CLAIMS)
    ) as mock_v:
        claims = verify_google_id_token("tok")
    assert claims["sub"] == "google-sub-001"
    mock_v.assert_called_once()
    # audience must be our client id
    assert mock_v.call_args.kwargs.get("audience") is not None


def test_verify_rejects_invalid_token():
    with patch("app.security.verify_oauth2_token", side_effect=ValueError("bad")):
        with pytest.raises(ValueError, match="invalid_token"):
            verify_google_id_token("tok")


def test_verify_rejects_unverified_email():
    claims = dict(GOOD_CLAIMS, email_verified=False)
    with patch("app.security.verify_oauth2_token", return_value=claims):
        with pytest.raises(ValueError, match="unverified_email"):
            verify_google_id_token("tok")


def test_verify_rejects_missing_sub():
    claims = dict(GOOD_CLAIMS)
    del claims["sub"]
    with patch("app.security.verify_oauth2_token", return_value=claims):
        with pytest.raises(ValueError, match="unverified_email"):
            verify_google_id_token("tok")
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `services/api`):

```powershell
& "D:\code\sayvors\.venv\Scripts\python.exe" -m pytest tests/test_google_signin.py -q
```

Expected: FAIL — `ImportError: cannot import name 'verify_google_id_token'`.

- [ ] **Step 3: Implement**

In `services/api/app/security.py`, append (keep existing imports; add
`from google.auth.transport import requests as google_auth_requests` and
`from google.oauth2.id_token import verify_oauth2_token` at the top):

```python
def verify_google_id_token(id_token: str) -> dict:
    """Verify a Google Identity Services ID token and return its claims.

    Checks signature (against Google's certs), audience, and expiry inside
    verify_oauth2_token, then enforces our own claim requirements.
    Raises ValueError("invalid_token") on cryptographic/audience failure and
    ValueError("unverified_email") when the token is well-formed but unusable
    for sign-in.
    """
    from .config import settings

    try:
        claims = verify_oauth2_token(
            id_token,
            google_auth_requests.Request(),
            audience=settings.GOOGLE_CLIENT_ID,
        )
    except Exception:
        raise ValueError("invalid_token")
    if not claims.get("sub") or not claims.get("email") or claims.get("email_verified") is not True:
        raise ValueError("unverified_email")
    return claims
```

Note: the tests patch `app.security.verify_oauth2_token` — the module-level
import is required for that patch target to work.

- [ ] **Step 4: Run tests to verify they pass**

```powershell
& "D:\code\sayvors\.venv\Scripts\python.exe" -m pytest tests/test_google_signin.py -q
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```powershell
git add services/api/app/security.py services/api/tests/test_google_signin.py
git commit -m "feat(auth): verify_google_id_token with signature/audience/email checks"
```

---

### Task 3: `google_login` service + shared session issuance (TDD)

**Files:**
- Modify: `services/api/app/modules/auth/events.py`
- Modify: `services/api/app/modules/auth/service.py`
- Test: append to `services/api/tests/test_google_signin.py`

- [ ] **Step 1: Extend `log_signup` / `log_login` with optional metadata**

In `services/api/app/modules/auth/events.py` replace the two functions:

```python
async def log_signup(user_id: str, email: str, ip: str, ua: str,
                     metadata: dict | None = None) -> None:
    """Record a successful user registration event."""

    await log_auth_event("signup", user_id=user_id, email=email, ip_address=ip,
                         user_agent=ua, metadata=metadata)


async def log_login(user_id: str, email: str, ip: str, ua: str,
                    metadata: dict | None = None) -> None:
    """Record a successful authentication event for an existing user."""

    await log_auth_event("login", user_id=user_id, email=email, ip_address=ip,
                         user_agent=ua, metadata=metadata)
```

(`log_auth_event` already accepts `metadata` — no other caller changes.)

- [ ] **Step 2: Write the failing service tests**

Append to `services/api/tests/test_google_signin.py`:

```python
async def test_google_signup_creates_user(db):
    from app.modules.auth.service import google_login
    from app.security import verify_password

    with patch("app.modules.auth.service.log_signup", new_callable=AsyncMock) as mock_ev:
        result = await google_login(dict(GOOD_CLAIMS), db, "UA-Test", "1.2.3.4")

    assert "access_token" in result and "refresh_token" in result
    u = await db.get(User, result["user"]["id"])
    assert u.google_sub == "google-sub-001"
    assert u.email_verified is True
    assert u.onboarded is False
    assert u.avatar_url == "https://img.example/p.png"
    assert (u.first_name, u.last_name) == ("G", "User")
    assert verify_password("anypassword1", u.password_hash) is False
    mock_ev.assert_awaited_once()
    assert mock_ev.call_args.kwargs.get("metadata") == {"via": "google"}


async def test_google_links_existing_password_account(db, user_id):
    from app.modules.auth.service import google_login
    from app.security import hash_password, verify_password

    db.add(User(id=user_id, email="guser@sayvors.com", first_name="Old",
                last_name="Name", password_hash=hash_password("Secret123!"),
                onboarded=True))
    await db.commit()

    with patch("app.modules.auth.service.log_login", new_callable=AsyncMock) as mock_ev:
        result = await google_login(dict(GOOD_CLAIMS), db, "UA", "1.2.3.4")

    assert result["user"]["id"] == user_id          # same account, not a new one
    u = await db.get(User, user_id)
    assert u.google_sub == "google-sub-001"         # linked
    assert verify_password("Secret123!", u.password_hash) is True  # password intact
    mock_ev.assert_awaited_once()


async def test_google_signin_refreshes_profile_snapshot(db):
    from app.modules.auth.service import google_login

    db.add(User(email="guser@sayvors.com", first_name="Old", last_name="Name",
                password_hash="x", email_verified=True, onboarded=True,
                google_sub="google-sub-001"))
    await db.commit()

    claims = dict(GOOD_CLAIMS, name="Fresh Name")
    with patch("app.modules.auth.service.log_login", new_callable=AsyncMock) as mock_ev:
        result = await google_login(claims, db, "UA", "1.2.3.4")

    u = await db.get(User, result["user"]["id"])
    assert (u.first_name, u.last_name) == ("Fresh", "Name")
    assert result["user"]["onboarded"] is True
    mock_ev.assert_awaited_once()
```

(Note: when `name` has no space, `last_name` stays `""` — the snapshot test
above covers the split-on-first-space rule with `"Fresh Name"`.)

- [ ] **Step 3: Run tests to verify they fail**

```powershell
& "D:\code\sayvors\.venv\Scripts\python.exe" -m pytest tests/test_google_signin.py -q
```

Expected: 3 new tests FAIL (`ImportError: cannot import name 'google_login'`);
the 4 Task-2 tests still PASS.

- [ ] **Step 4: Implement in `auth/service.py`**

Top-of-file import changes (extend the existing `from sqlalchemy import ...`
line and add the exception import):

```python
from sqlalchemy import select, delete, update, func
from sqlalchemy.exc import IntegrityError
```

Append after `login()` (before `refresh_tokens`):

```python
async def _issue_session(user: User, db: AsyncSession, event: str,
                         user_agent: str, ip: str,
                         metadata: dict | None = None) -> dict:
    """Access + refresh tokens, refresh row, Redis session, auth event.
    The single session-issuance path shared by Google sign-in."""
    access_token = create_access_token(user.id, user.token_version or 0)
    refresh_raw = create_refresh_token(user.id)
    db.add(RefreshToken(
        user_id=user.id,
        token_hash=hash_token(refresh_raw),
        fingerprint=create_token_fingerprint(user_agent, ip),
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.JWT_REFRESH_EXPIRATION_DAYS),
        user_agent=user_agent[:500],
        ip_address=ip[:45],
    ))
    await db.commit()

    try:
        from ...modules.redis.client import get_redis
        redis = await get_redis()
        session_data = {"user_id": user.id, "ip": ip, "user_agent": user_agent[:200]}
        await store_session(user.id, user.id, session_data,
                            settings.JWT_REFRESH_EXPIRATION_DAYS * 86400)
    except Exception:
        pass

    if event == "signup":
        await log_signup(user.id, user.email, ip, user_agent[:200], metadata=metadata)
    else:
        await log_login(user.id, user.email, ip, user_agent[:200], metadata=metadata)

    return {
        "access_token": access_token,
        "refresh_token": refresh_raw,
        "user": {
            "id": user.id,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "email": user.email,
            "email_verified": user.email_verified,
            "onboarded": user.onboarded,
        },
    }


async def google_login(claims: dict, db: AsyncSession,
                       user_agent: str, ip: str) -> dict:
    """Find-or-create from verified Google claims; issue a session.

    Google's tokens are never stored — only the profile snapshot lands on the
    user row (google_sub / name / avatar_url).
    """
    import secrets as _secrets

    sub = claims["sub"]
    email = claims["email"].strip().lower()
    name = (claims.get("name") or "").strip()
    picture = claims.get("picture")
    first, _sep, last = name.partition(" ")
    if not first:
        first = email.split("@", 1)[0]
        last = ""

    try:
        event = "login"
        result = await db.execute(select(User).where(User.google_sub == sub))
        user = result.scalar_one_or_none()

        if user is None:
            result = await db.execute(
                select(User).where(func.lower(User.email) == email)
            )
            user = result.scalar_one_or_none()
            if user is not None:
                # Decision 1A: link — existing password account adopts Google.
                if user.google_sub is None:
                    user.google_sub = sub
                if picture:
                    user.avatar_url = picture
            else:
                user = User(
                    first_name=first[:100],
                    last_name=last[:100],
                    email=email,
                    password_hash=hash_password(_secrets.token_urlsafe(32)),
                    email_verified=True,
                    onboarded=False,
                    google_sub=sub,
                    avatar_url=picture,
                )
                db.add(user)
                event = "signup"
        else:
            if first:
                user.first_name = first[:100]
            if last:
                user.last_name = last[:100]
            if picture:
                user.avatar_url = picture

        return await _issue_session(user, db, event, user_agent, ip,
                                    metadata={"via": "google"})
    except IntegrityError:
        # Concurrent signup race: the row exists now — sign in with it.
        await db.rollback()
        result = await db.execute(select(User).where(User.google_sub == sub))
        user = result.scalar_one_or_none()
        if user is None:
            raise ValueError("Could not create account")
        return await _issue_session(user, db, "login", user_agent, ip,
                                    metadata={"via": "google"})
```

- [ ] **Step 5: Run tests to verify they pass**

```powershell
& "D:\code\sayvors\.venv\Scripts\python.exe" -m pytest tests/test_google_signin.py -q
```

Expected: 7 passed.

- [ ] **Step 6: Commit**

```powershell
git add services/api/app/modules/auth/events.py services/api/app/modules/auth/service.py services/api/tests/test_google_signin.py
git commit -m "feat(auth): google_login find-or-create with shared session issuance"
```

---

### Task 4: `POST /auth/google/verify` endpoint (TDD)

**Files:**
- Modify: `services/api/app/modules/auth/schemas.py`
- Modify: `services/api/app/modules/auth/router.py`
- Test: append to `services/api/tests/test_google_signin.py`

- [ ] **Step 1: Write the failing endpoint tests**

Append to `services/api/tests/test_google_signin.py`:

```python
async def test_verify_endpoint_success(client, db, user_id):
    with (
        patch("app.modules.auth.router.rate_limit", new_callable=AsyncMock, return_value=True),
        patch("app.modules.auth.router.verify_google_id_token", return_value=dict(GOOD_CLAIMS)),
        patch("app.modules.auth.service.log_signup", new_callable=AsyncMock),
    ):
        resp = client.post(
            "/api/v1/auth/google/verify",
            json={"id_token": "tok"},
            headers={"User-Agent": "UA"},
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" not in data          # refresh travels as httpOnly cookie
    assert set(data["user"]) == {
        "id", "first_name", "last_name", "email", "email_verified", "onboarded",
    }
    assert data["user"]["email"] == "guser@sayvors.com"
    u = await db.get(User, data["user"]["id"])
    assert u.google_sub == "google-sub-001"


async def test_verify_endpoint_401_on_invalid_token(client):
    with (
        patch("app.modules.auth.router.rate_limit", new_callable=AsyncMock, return_value=True),
        patch("app.modules.auth.router.verify_google_id_token",
              side_effect=ValueError("invalid_token")),
    ):
        resp = client.post("/api/v1/auth/google/verify", json={"id_token": "bad"})
    assert resp.status_code == 401
    assert "Google sign-in failed" in resp.json()["detail"]


async def test_verify_endpoint_400_on_unverified_email(client):
    with (
        patch("app.modules.auth.router.rate_limit", new_callable=AsyncMock, return_value=True),
        patch("app.modules.auth.router.verify_google_id_token",
              side_effect=ValueError("unverified_email")),
    ):
        resp = client.post("/api/v1/auth/google/verify", json={"id_token": "tok"})
    assert resp.status_code == 400


async def test_verify_endpoint_503_without_config(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "")
    with patch("app.modules.auth.router.rate_limit",
               new_callable=AsyncMock, return_value=True):
        resp = client.post("/api/v1/auth/google/verify", json={"id_token": "tok"})
    assert resp.status_code == 503
    assert "GOOGLE_CLIENT_ID" in resp.json()["detail"]
```

- [ ] **Step 2: Run tests to verify they fail**

```powershell
& "D:\code\sayvors\.venv\Scripts\python.exe" -m pytest tests/test_google_signin.py -q
```

Expected: 4 new FAIL with 404 (route does not exist); 7 older PASS.

- [ ] **Step 3: Add the schema**

In `services/api/app/modules/auth/schemas.py`, after `LoginRequest`:

```python
class GoogleVerifyRequest(BaseModel):
    id_token: str = Field(..., min_length=10, max_length=20000)
```

- [ ] **Step 4: Add the endpoint**

In `services/api/app/modules/auth/router.py`:

1. Extend the `from ...security import ...` line to also import
   `verify_google_id_token`.
2. Add `GoogleVerifyRequest` to the `from .schemas import (...)` list.
3. Add `google_login` to the `from .service import (...)` list.
4. Append the endpoint (after `/reset-password`, before `/verify-email`):

```python
@router.post("/google/verify")
async def google_verify_endpoint(
    body: GoogleVerifyRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Sign in / sign up / link via a Google Identity Services ID token.

    The token is verified server-side (signature, audience, expiry, verified
    email); Google's tokens are discarded and only the profile snapshot is
    stored. Session issuance is identical to password login."""
    ip = get_client_ip(request)
    user_agent = request.headers.get("user-agent", "")

    if not await rate_limit(f"google:{ip}", 30, 60):
        raise HTTPException(status_code=429, detail="Too many attempts. Try again later.")
    if not settings.GOOGLE_CLIENT_ID:
        raise HTTPException(
            status_code=503,
            detail="Google Sign-In not configured. Set GOOGLE_CLIENT_ID in .env",
        )

    try:
        claims = verify_google_id_token(body.id_token)
    except ValueError as e:
        if str(e) == "unverified_email":
            raise HTTPException(
                status_code=400,
                detail="Google account email is not verified.",
            )
        raise HTTPException(status_code=401, detail="Google sign-in failed")

    try:
        result = await google_login(claims, db, user_agent, ip)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    refresh_token = result.pop("refresh_token")
    _set_session_cookies(response, refresh_token)
    return result
```

- [ ] **Step 5: Run tests to verify they pass**

```powershell
& "D:\code\sayvors\.venv\Scripts\python.exe" -m pytest tests/test_google_signin.py -q
```

Expected: 11 passed.

- [ ] **Step 6: Commit**

```powershell
git add services/api/app/modules/auth/schemas.py services/api/app/modules/auth/router.py services/api/tests/test_google_signin.py
git commit -m "feat(auth): POST /auth/google/verify endpoint"
```

---

### Task 5: `googleLogin` in auth-context

**Files:**
- Modify: `apps/web/lib/auth-context.tsx`

- [ ] **Step 1: Add the type to the context interface**

In `apps/web/lib/auth-context.tsx`, in `AuthContextType` after the `login`
line (line 26):

```typescript
  googleLogin: (idToken: string) => Promise<User>;
```

- [ ] **Step 2: Implement the function**

After the `login` function (ends around line 181):

```typescript
  const googleLogin = async (idToken: string): Promise<User> => {
    const res = await apiFetch("/api/v1/auth/google/verify", {
      method: "POST",
      body: JSON.stringify({ id_token: idToken }),
    });

    if (!res.ok) {
      const err = await res.json();
      const detail = (err as any).detail;
      throw new Error(typeof detail === "string" ? detail : "Google sign-in failed");
    }

    const result = await res.json();
    if (result.access_token) setAccessToken(result.access_token);
    setUser(result.user);
    return result.user as User;
  };
```

- [ ] **Step 3: Expose it in the provider value**

In the `<AuthContext.Provider value={{ ... }}>` object, after `login,`:

```typescript
        googleLogin,
```

- [ ] **Step 4: Type-check**

Run (from `apps/web`):

```powershell
npx tsc --noEmit
```

Expected: no new errors (4 known-safe; the repo must be clean of *new* ones).

- [ ] **Step 5: Commit**

```powershell
git add lib/auth-context.tsx
git commit -m "feat(web): googleLogin in auth context"
```

---

### Task 6: Wire the GIS button in AuthForm

**Files:**
- Modify: `apps/web/components/AuthForm.tsx` (Google stub at lines 325–329)
- Create: `apps/web/.env.example`

- [ ] **Step 1: Imports + state + destructure**

In `apps/web/components/AuthForm.tsx`:

1. Line 6 — add `useEffect` and `useRef`:

```typescript
import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
```

2. Line 175 — pull `googleLogin` from the context:

```typescript
  const { signup, login, googleLogin } = useAuth();
```

3. After the `error` state (line 186) add:

```typescript
  const googleBtnRef = useRef<HTMLDivElement>(null);
  const [gisFailed, setGisFailed] = useState(false);
```

- [ ] **Step 2: Load GIS and render the official button**

Add this `useEffect` immediately after the state declarations:

```typescript
  useEffect(() => {
    const clientId = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID;
    if (!clientId) return;
    const w = window as any;
    const init = () => {
      try {
        w.google.accounts.id.initialize({
          client_id: clientId,
          callback: async ({ credential }: { credential: string }) => {
            try {
              const u = await googleLogin(credential);
              window.location.href = u?.onboarded ? "/dashboard" : "/onboarding";
            } catch {
              setNote("Google sign-in failed. Try again or use your password.");
            }
          },
        });
        if (googleBtnRef.current) {
          w.google.accounts.id.renderButton(googleBtnRef.current, {
            theme: "outline",
            size: "large",
            text: "continue_with",
            width: Math.min(googleBtnRef.current.offsetWidth || 360, 400),
          });
        }
      } catch {
        setGisFailed(true);
      }
    };
    if (w.google?.accounts?.id) {
      init();
      return;
    }
    const s = document.createElement("script");
    s.src = "https://accounts.google.com/gsi/client";
    s.async = true;
    s.onload = init;
    s.onerror = () => setGisFailed(true);
    document.head.appendChild(s);
    // Init once on mount; googleLogin identity is stable enough for this use.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
```

Notes:
- Plain `<script>` element loading on purpose — no Next.js script APIs, per
  `apps/web/AGENTS.md` (this Next version has breaking changes; verify against
  `node_modules/next/dist/docs/` if anything unexpected appears).
- Redirect target honors Decision 4: `onboarded=false` → `/onboarding`.
- GIS is rendered by Google into the div (official branding rules); the
  container stretches it to full width.

- [ ] **Step 3: Replace the stub button**

Replace the existing Google stub (lines 325–329):

```tsx
        <button type="button" onClick={() => setNote("Google sign-in coming soon.")}
          className="flex h-11 w-full items-center justify-center gap-2.5 rounded-lg border border-ink/[0.12] text-[14px] font-medium text-ink/70 transition-all duration-200 hover:border-ink/20 hover:bg-ink/[0.02] active:scale-[0.99]">
          <Image src="/google.svg" alt="" width={18} height={18} className="h-[18px] w-[18px]" />
          Continue with Google
        </button>
```

with:

```tsx
        {!gisFailed && process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID && (
          <div ref={googleBtnRef} className="min-h-11 w-full [&>div]:!w-full" />
        )}
```

(The GitHub "coming soon" button below it stays untouched.)

- [ ] **Step 4: Create `apps/web/.env.example`**

```dotenv
# Public API base URL (no trailing slash)
NEXT_PUBLIC_API_URL=http://localhost:8000

# Google Identity Services client id (same project as GOOGLE_CLIENT_ID).
# Leave empty to hide the "Continue with Google" button.
NEXT_PUBLIC_GOOGLE_CLIENT_ID=
```

Also append to `deploy/env.prod.example`:

```dotenv
NEXT_PUBLIC_GOOGLE_CLIENT_ID=
```

- [ ] **Step 5: Type-check**

Run (from `apps/web`):

```powershell
npx tsc --noEmit
```

Expected: no new errors.

- [ ] **Step 6: Commit**

```powershell
git add components/AuthForm.tsx .env.example ../deploy/env.prod.example
git commit -m "feat(web): Continue with Google button via GIS on auth form"
```

---

### Task 7: Full verification

**Files:** none (verification only)

- [ ] **Step 1: Full backend suite**

Run (from `services/api`):

```powershell
& "D:\code\sayvors\.venv\Scripts\python.exe" -m pytest -q 2>&1 | Select-Object -Last 8
```

Expected: 11 new Google tests PASS; **only** the 4 known pre-existing
failures remain (`test_admin_health_structure`, `test_overview_empty`,
`test_autoreply_model_restricted_to_admin_enabled`,
`test_period_bounds_equal_length`). Any other failure = regression from this
plan — fix before proceeding.

- [ ] **Step 2: Frontend type-check**

```powershell
npx tsc --noEmit
```

Expected: no new errors.

- [ ] **Step 3: Manual smoke checklist (local, needs real client id)**

With `GOOGLE_CLIENT_ID` + `NEXT_PUBLIC_GOOGLE_CLIENT_ID` set to a real Google
Cloud OAuth client (type: Web; Authorized JavaScript origins:
`http://localhost:3000`):

1. `/signup` → "Continue with Google" → consent → lands on `/onboarding`
   (new account, `email_verified=true`).
2. Log out → `/login` → Google again → same account, lands on `/dashboard`.
3. Create a password account with email X → log out → Google with an account
   of email X → lands on `/dashboard` as the SAME user (linked; password still
   works).
4. Wrong/missing client id → button hidden, password flow unaffected.

Record results in the checkboxes; no code change needed if all pass.

- [ ] **Step 4: Final status review**

```powershell
git status --short
git log --oneline -7
```

Expected: 6 feature commits present; user WIP (OTP hardening, typed `/me`,
onboarding page, etc.) still uncommitted. **Do not push** unless the user says
"push".







