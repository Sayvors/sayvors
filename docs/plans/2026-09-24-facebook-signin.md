# Facebook Sign-In Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** "Continue with Facebook" on login/signup with Google-identical semantics, plus visible (never silent) UX states and welcome email on all social signups.

**Architecture:** Client FB SDK (same-origin proxied bundle) + `FB.login` popup → `POST /auth/facebook/verify` validates the token via Graph `debug_token`, then find-or-create reuses the shared `_issue_session`. Tokens discarded.

**Tech Stack:** FastAPI + SQLAlchemy async + Alembic, Next.js (plain `<script>` injection, no Next script APIs per `apps/web/AGENTS.md`), FB JS SDK v26.0, Graph API v26.0, pytest, tsc.

---

## File map

| File | Responsibility |
|------|---------------|
| `services/api/app/modules/users/models.py` | Add `facebook_id` column |
| `services/api/alembic/versions/<new>_users_facebook_identity.py` | Migration (new head) |
| `services/api/app/config.py` | `META_LOGIN_APP_ID/SECRET` + fallback properties |
| `services/api/app/security.py` | `verify_facebook_token()` |
| `services/api/app/modules/auth/service.py` | `facebook_login()`, `_send_welcome_email()` helper, Google retrofit |
| `services/api/app/modules/auth/schemas.py` | `FacebookVerifyRequest` |
| `services/api/app/modules/auth/router.py` | `POST /auth/facebook/verify` (selective-stage: user's `UpdateMeRequest` WIP stays unstaged) |
| `services/api/app/main.py` | CSRF exempt `+ "/api/v1/auth/facebook/verify"` |
| `services/api/tests/test_facebook_signin.py` | New: 11 tests mirroring Google's |
| `services/api/tests/test_google_signin.py` | Append: Google welcome-email test |
| `services/api/.env.example`, `deploy/env.prod.example` | New backend vars (selective-stage the latter) |
| `apps/web/lib/auth-context.tsx` | `facebookLogin()` |
| `apps/web/components/AuthForm.tsx` | FB button + SDK loader + states; delete GitHub stub |
| `apps/web/public/facebook.svg` | New: "f" logo, same 48px canvas as `google.svg` |
| `apps/web/.env.example`, `deploy/env.prod.example` | `NEXT_PUBLIC_META_LOGIN_APP_ID` |

> Spec deviation (improvement, spec updated): the FB SDK loads from the
> same-origin proxy `${API_URL}/api/v1/meta/connect-sdk` (established in
> `channels/meta/router.py`, ad-blocker-proof) instead of `connect.facebook.net`.
> Consequence: **no CSP change needed** (`script-src` already allows the API host;
> `frame-src`/`connect-src` already cover facebook.com/graph).

---

### Task 1: Migration + `facebook_id` column

**Files:**
- Modify: `services/api/app/modules/users/models.py` (after `avatar_url`, ~line 38)
- Create: `services/api/alembic/versions/<generated>_users_facebook_identity.py` via autogenerate

- [ ] **Step 1: Add the column**

```python
    # Facebook identity (Continue with Facebook). Mirrors google_sub.
    facebook_id: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True, index=True)
```

- [ ] **Step 2: Generate + inspect migration**

```powershell
& "D:\code\sayvors\.venv\Scripts\python.exe" -m alembic revision --autogenerate -m "users_facebook_identity"
```

Expected: new file; must contain `op.add_column("users", sa.Column("facebook_id", ...))`,
unique index, and a working `downgrade()` dropping both. Fix by hand if autogenerate misses.

- [ ] **Step 3: Round-trip**

```powershell
& "D:\code\sayvors\.venv\Scripts\python.exe" -m alembic upgrade head; if ($?) { & "D:\code\sayvors\.venv\Scripts\python.exe" -m alembic downgrade -1; if ($?) { & "D:\code\sayvors\.venv\Scripts\python.exe" -m alembic upgrade head } }; & "D:\code\sayvors\.venv\Scripts\python.exe" -m alembic current
```

Expected: ends on the new head, no errors.

- [ ] **Step 4: Commit**

```powershell
git add services/api/app/modules/users/models.py services/api/alembic/versions/<file>.py
git commit -m "feat(users): facebook_id column for Facebook sign-in"
```

---

### Task 2: Login-app config with fallback

**Files:**
- Modify: `services/api/app/config.py` (after `META_APP_SECRET`, line 125)
- Modify: `services/api/.env.example` (append vars)
- Modify: `deploy/env.prod.example` (append var; SELECTIVE-STAGE — user WIP present)
- Test: new `services/api/tests/test_facebook_signin.py` (config test first)

- [ ] **Step 1: Failing config test**

```python
def test_login_app_fallback(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "META_APP_ID", "app1")
    monkeypatch.setattr(settings, "META_APP_SECRET", "sec1")
    monkeypatch.setattr(settings, "META_LOGIN_APP_ID", "")
    monkeypatch.setattr(settings, "META_LOGIN_APP_SECRET", "")
    assert settings.facebook_login_app_id == "app1"
    assert settings.facebook_login_app_secret == "sec1"
    monkeypatch.setattr(settings, "META_LOGIN_APP_ID", "app2")
    monkeypatch.setattr(settings, "META_LOGIN_APP_SECRET", "sec2")
    assert settings.facebook_login_app_id == "app2"
    assert settings.facebook_login_app_secret == "sec2"
```

- [ ] **Step 2: Run (expect 1 failed — `AttributeError: facebook_login_app_id`)**

```powershell
& "D:\code\sayvors\.venv\Scripts\python.exe" -m pytest tests/test_facebook_signin.py -q 2>&1 | Select-Object -Last 3
```

- [ ] **Step 3: Implement in `config.py`**

```python
    META_APP_ID: str = ""
    META_APP_SECRET: str = ""
    # Dedicated user-login app (Continue with Facebook). Empty = fall back to
    # the platform META_APP_ID/SECRET (same values for now; split later by env only).
    META_LOGIN_APP_ID: str = ""
    META_LOGIN_APP_SECRET: str = ""

    @property
    def facebook_login_app_id(self) -> str:
        return self.META_LOGIN_APP_ID or self.META_APP_ID

    @property
    def facebook_login_app_secret(self) -> str:
        return self.META_LOGIN_APP_SECRET or self.META_APP_SECRET
```

- [ ] **Step 4: Run (expect 1 passed)**

```powershell
& "D:\code\sayvors\.venv\Scripts\python.exe" -m pytest tests/test_facebook_signin.py -q 2>&1 | Select-Object -Last 2
```

- [ ] **Step 5: `.env.example` files** — append to `services/api/.env.example`:

```dotenv
# Dedicated Facebook Login app for user sign-in. Leave empty to reuse META_APP_ID/SECRET.
META_LOGIN_APP_ID=
META_LOGIN_APP_SECRET=
```

and to `deploy/env.prod.example` (same two lines), then selective-stage only those
lines via `filter_hunks.py` with marker `META_LOGIN_APP` (user's DATABASE_URL WIP stays unstaged).

- [ ] **Step 6: Commit**

```powershell
git add services/api/app/config.py services/api/tests/test_facebook_signin.py services/api/.env.example
git commit -m "feat(auth): login-app config with META fallback"
```

(deploy/env.prod.example hunk applied with `git apply --cached` in Step 5 — include it in this commit only if the staged diff shows exactly the 2 added lines.)

---

### Task 3: `verify_facebook_token` (TDD)

**Files:**
- Modify: `services/api/app/security.py` (needs `import httpx` at top)
- Test: append to `services/api/tests/test_facebook_signin.py`

- [ ] **Step 1: Failing tests**

```python
from unittest.mock import patch

import httpx
import pytest

from app.security import verify_facebook_token

FB_ME = {"id": "fb-123", "name": "Ada Lovelace", "email": "ada@example.com",
         "picture": {"data": {"url": "https://pic/x.jpg"}}}


def _resp(payload):
    m = Mock()
    m.json.return_value = payload
    return m


def test_facebook_verify_ok(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "META_APP_ID", "app1")
    monkeypatch.setattr(settings, "META_APP_SECRET", "sec1")
    monkeypatch.setattr(settings, "META_LOGIN_APP_ID", "")
    monkeypatch.setattr(settings, "META_LOGIN_APP_SECRET", "")
    with patch("app.security.httpx.get", side_effect=[
        _resp({"data": {"is_valid": True, "app_id": "app1"}}),
        _resp(dict(FB_ME)),
    ]) as mock_get:
        profile = verify_facebook_token("user-token")
    assert profile == {"id": "fb-123", "email": "ada@example.com",
                       "name": "Ada Lovelace", "picture": "https://pic/x.jpg"}
    assert mock_get.call_count == 2


def test_facebook_verify_wrong_app(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "META_APP_ID", "app1")
    monkeypatch.setattr(settings, "META_APP_SECRET", "sec1")
    with patch("app.security.httpx.get",
               return_value=_resp({"data": {"is_valid": True, "app_id": "OTHER"}})):
        with pytest.raises(ValueError, match="invalid_token"):
            verify_facebook_token("tok")


def test_facebook_verify_invalid(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "META_APP_ID", "app1")
    monkeypatch.setattr(settings, "META_APP_SECRET", "sec1")
    with patch("app.security.httpx.get",
               return_value=_resp({"data": {"is_valid": False}})):
        with pytest.raises(ValueError, match="invalid_token"):
            verify_facebook_token("tok")


def test_facebook_verify_missing_email(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "META_APP_ID", "app1")
    monkeypatch.setattr(settings, "META_APP_SECRET", "sec1")
    me = dict(FB_ME)
    del me["email"]
    with patch("app.security.httpx.get", side_effect=[
        _resp({"data": {"is_valid": True, "app_id": "app1"}}),
        _resp(me),
    ]):
        with pytest.raises(ValueError, match="unverified_email"):
            verify_facebook_token("tok")


def test_facebook_verify_network_error(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "META_APP_ID", "app1")
    monkeypatch.setattr(settings, "META_APP_SECRET", "sec1")
    with patch("app.security.httpx.get", side_effect=httpx.ConnectError("down")):
        with pytest.raises(ValueError, match="invalid_token"):
            verify_facebook_token("tok")
```

(`Mock` import: `from unittest.mock import Mock, patch` at the top of the test additions.)

- [ ] **Step 2: Run (expect 5 failed — `ImportError: cannot import name 'verify_facebook_token'`)**

```powershell
& "D:\code\sayvors\.venv\Scripts\python.exe" -m pytest tests/test_facebook_signin.py -q 2>&1 | Select-Object -Last 3
```

Expected: 5 failed, 1 passed (config test).

- [ ] **Step 3: Implement in `security.py`** (add `import httpx` to imports):

```python
def verify_facebook_token(access_token: str) -> dict:
    """Validate a Facebook Login user token; return a normalized profile.

    1. `debug_token` with the app token proves the token was issued to OUR
       login app (wrong-app tokens are attacker-controlled). 2. `/me` fetches
       the profile. Raises ValueError("invalid_token") on any auth/network
       failure (cause logged, token never logged), ValueError("unverified_email")
       when id/email are missing, ValueError("unconfigured") when no app id.
    """
    app_id = settings.facebook_login_app_id
    app_secret = settings.facebook_login_app_secret
    if not app_id or not app_secret:
        raise ValueError("unconfigured")
    base = f"https://graph.facebook.com/{settings.META_GRAPH_API_VERSION}"
    try:
        dbg = httpx.get(
            f"{base}/debug_token",
            params={"input_token": access_token, "access_token": f"{app_id}|{app_secret}"},
            timeout=10,
        ).json().get("data", {})
        if not dbg.get("is_valid") or str(dbg.get("app_id")) != str(app_id):
            raise ValueError("invalid_token")
        me = httpx.get(
            f"{base}/me",
            params={"fields": "id,name,email,picture.type(large)", "access_token": access_token},
            timeout=10,
        ).json()
        if not me.get("id") or not me.get("email"):
            raise ValueError("unverified_email")
        picture = ((me.get("picture") or {}).get("data") or {}).get("url")
        return {"id": me["id"], "email": me["email"],
                "name": me.get("name", ""), "picture": picture}
    except ValueError:
        raise
    except Exception as e:
        logger.warning("Facebook token verification failed: %s: %s", type(e).__name__, e)
        raise ValueError("invalid_token")
```

- [ ] **Step 4: Run (expect 6 passed)**

```powershell
& "D:\code\sayvors\.venv\Scripts\python.exe" -m pytest tests/test_facebook_signin.py -q 2>&1 | Select-Object -Last 2
```

- [ ] **Step 5: Commit**

```powershell
git add services/api/app/security.py services/api/tests/test_facebook_signin.py
git commit -m "feat(auth): verify_facebook_token via Graph debug_token"
```

---

### Task 4: `facebook_login` + welcome-email helper + Google retrofit (TDD)

**Files:**
- Modify: `services/api/app/modules/auth/service.py`
- Test: append service tests to `services/api/tests/test_facebook_signin.py`;
  append one test to `services/api/tests/test_google_signin.py`

- [ ] **Step 1: Failing tests** (append; reuse the file's existing imports/fixtures:
  `db`, `client`, `user_id`, `User`, `patch`, `AsyncMock`, `GOOD_CLAIMS`-style profile)

```python
FB_PROFILE = {"id": "fb-123", "email": "fbuser@sayvors.com",
              "name": "FB User", "picture": "https://pic/fb.jpg"}


async def test_facebook_signup_creates_user(db):
    from app.modules.auth.service import facebook_login

    with (
        patch("app.modules.auth.service.log_signup", new_callable=AsyncMock) as mock_ev,
        patch("app.modules.auth.service.send_welcome_email", new_callable=AsyncMock) as mock_mail,
    ):
        result = await facebook_login(dict(FB_PROFILE), db, "UA", "1.2.3.4")

    assert result["user"]["email"] == "fbuser@sayvors.com"
    assert result["user"]["onboarded"] is False
    assert result["user"]["email_verified"] is True
    assert "access_token" in result and "refresh_token" in result
    u = await db.get(User, result["user"]["id"])
    assert u.facebook_id == "fb-123"
    assert u.avatar_url == "https://pic/fb.jpg"
    assert u.google_sub is None
    mock_ev.assert_awaited_once()
    mock_mail.assert_awaited_once()


async def test_facebook_links_existing_password_account(db, user_id):
    from app.modules.auth.service import facebook_login

    before = await db.get(User, user_id)
    pw_hash = before.password_hash
    with (
        patch("app.modules.auth.service.log_login", new_callable=AsyncMock),
        patch("app.modules.auth.service.send_welcome_email", new_callable=AsyncMock) as mock_mail,
    ):
        # user_id fixture email must equal FB_PROFILE email (adjust fixture or profile)
        result = await facebook_login(dict(FB_PROFILE), db, "UA", "1.2.3.4")

    assert result["user"]["id"] == user_id
    after = await db.get(User, user_id)
    assert after.facebook_id == "fb-123"
    assert after.password_hash == pw_hash          # password login still works
    mock_mail.assert_not_awaited()                 # link = login, not signup


async def test_google_signup_sends_welcome_email(db):
    # Retrofit check (Task 4 also patches google_login) — append to test_google_signin.py
    from app.modules.auth.service import google_login

    with (
        patch("app.modules.auth.service.log_signup", new_callable=AsyncMock),
        patch("app.modules.auth.service.send_welcome_email", new_callable=AsyncMock) as mock_mail,
    ):
        await google_login(dict(GOOD_CLAIMS), db, "UA", "1.2.3.4")
    mock_mail.assert_awaited_once()
```

Notes: `send_welcome_email` must be importable as
`app.modules.auth.service.send_welcome_email` — import it at module top of
`service.py` (it is Resend-backed and safe to import; calls stay fire-and-forget).
The link test needs the `user_id` fixture user to carry the FB email — check the
fixture in `test_google_signin.py` (Google link test already does this; mirror it:
create the fixture user with `FB_PROFILE["email"]` or parametrize). Adjust the test,
not the implementation, if the fixture email differs.

- [ ] **Step 2: Run (expect 3 failed — `ImportError: facebook_login` / welcome assertion)**

```powershell
& "D:\code\sayvors\.venv\Scripts\python.exe" -m pytest tests/test_facebook_signin.py tests/test_google_signin.py -q 2>&1 | Select-Object -Last 4
```

- [ ] **Step 3: Implement in `service.py`**

First, top-of-module import (find the existing email-service imports; add):

```python
from ...modules.email.service import send_welcome_email
```

Then the shared helper (place directly above `google_login`):

```python
async def _send_welcome_email(user: User) -> None:
    """Fire-and-forget greeting for brand-new social signups. Never fail signup."""
    try:
        await send_welcome_email(user.email, user.first_name or "there")
    except Exception:
        import logging
        logging.getLogger(__name__).warning("Welcome email failed for %s", user.email)
```

Then retrofit `google_login`: replace

```python
        return await _issue_session(user, db, event, user_agent, ip,
                                    metadata={"via": "google"})
    except IntegrityError:
```

with

```python
        result = await _issue_session(user, db, event, user_agent, ip,
                                      metadata={"via": "google"})
        if event == "signup":
            await _send_welcome_email(user)
        return result
    except IntegrityError:
```

(leave the retry path returning login unchanged — a race signup resolves to login, no email.)

Then append `facebook_login` after `google_login` (before `refresh_tokens`).
It is `google_login` with the claim shape changed (`id` instead of `sub`,
`picture` flat instead of nested) and `facebook_id` instead of `google_sub`:

```python
async def facebook_login(profile: dict, db: AsyncSession,
                         user_agent: str, ip: str) -> dict:
    """Find-or-create from a verified Facebook profile; issue a session.

    Mirrors google_login: Meta's tokens are never stored — only the profile
    snapshot lands on the user row (facebook_id / name / avatar_url).
    """
    import secrets as _secrets

    fb_id = profile["id"]
    email = profile["email"].strip().lower()
    name = (profile.get("name") or "").strip()
    picture = profile.get("picture")
    first, _sep, last = name.partition(" ")
    if not first:
        first = email.split("@", 1)[0]
        last = ""

    try:
        event = "login"
        result = await db.execute(select(User).where(User.facebook_id == fb_id))
        user = result.scalar_one_or_none()

        if user is None:
            result = await db.execute(
                select(User).where(func.lower(User.email) == email)
            )
            user = result.scalar_one_or_none()
            if user is not None:
                # Link — existing password account adopts Facebook.
                if user.facebook_id is None:
                    user.facebook_id = fb_id
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
                    facebook_id=fb_id,
                    avatar_url=picture,
                )
                db.add(user)
                await db.flush()  # assign user.id before the refresh-token row
                event = "signup"
        else:
            if first:
                user.first_name = first[:100]
            if last:
                user.last_name = last[:100]
            if picture:
                user.avatar_url = picture

        result = await _issue_session(user, db, event, user_agent, ip,
                                      metadata={"via": "facebook"})
        if event == "signup":
            await _send_welcome_email(user)
        return result
    except IntegrityError:
        # Concurrent signup race: the row exists now — sign in with it.
        await db.rollback()
        result = await db.execute(select(User).where(User.facebook_id == fb_id))
        user = result.scalar_one_or_none()
        if user is None:
            raise ValueError("Could not create account")
        return await _issue_session(user, db, "login", user_agent, ip,
                                    metadata={"via": "facebook"})
```

- [ ] **Step 4: Run (expect all pass in both files)**

```powershell
& "D:\code\sayvors\.venv\Scripts\python.exe" -m pytest tests/test_facebook_signin.py tests/test_google_signin.py -q 2>&1 | Select-Object -Last 2
```

Expected: `22 passed` (7 FB file so far incl. config test + 5 verify + ... count varies;
requirement: 0 failed).

- [ ] **Step 5: Commit**

```powershell
git add services/api/app/modules/auth/service.py services/api/tests/test_facebook_signin.py services/api/tests/test_google_signin.py
git commit -m "feat(auth): facebook_login find-or-create, welcome email on social signup"
```

---

### Task 5: `POST /auth/facebook/verify` endpoint (TDD)

**Files:**
- Modify: `services/api/app/modules/auth/schemas.py` (append `FacebookVerifyRequest`)
- Modify: `services/api/app/modules/auth/router.py` (imports + endpoint;
  SELECTIVE-STAGE — user's `UpdateMeRequest` WIP is still unstaged there)
- Modify: `services/api/app/main.py` (CSRF exempt `+ "/api/v1/auth/facebook/verify"`)
- Test: append 4 endpoint tests to `services/api/tests/test_facebook_signin.py`

- [ ] **Step 1: Failing endpoint tests**

```python
async def test_fb_verify_endpoint_success(client, db, user_id):
    with (
        patch("app.modules.auth.router.rate_limit", new_callable=AsyncMock, return_value=True),
        patch("app.modules.auth.router.verify_facebook_token", return_value=dict(FB_PROFILE)),
        patch("app.modules.auth.service.log_signup", new_callable=AsyncMock),
    ):
        resp = client.post(
            "/api/v1/auth/facebook/verify",
            json={"access_token": "test-fb-token-abc123"},
            headers={"User-Agent": "UA"},
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" not in data          # refresh travels as httpOnly cookie
    assert set(data["user"]) == {
        "id", "first_name", "last_name", "email", "email_verified", "onboarded",
    }
    u = await db.get(User, data["user"]["id"])
    assert u.facebook_id == "fb-123"


async def test_fb_verify_endpoint_401_on_invalid_token(client):
    with (
        patch("app.modules.auth.router.rate_limit", new_callable=AsyncMock, return_value=True),
        patch("app.modules.auth.router.verify_facebook_token",
              side_effect=ValueError("invalid_token")),
    ):
        resp = client.post("/api/v1/auth/facebook/verify",
                           json={"access_token": "test-fb-token-abc123"})
    assert resp.status_code == 401
    assert "Facebook sign-in failed" in resp.json()["detail"]


async def test_fb_verify_endpoint_400_on_missing_email(client):
    with (
        patch("app.modules.auth.router.rate_limit", new_callable=AsyncMock, return_value=True),
        patch("app.modules.auth.router.verify_facebook_token",
              side_effect=ValueError("unverified_email")),
    ):
        resp = client.post("/api/v1/auth/facebook/verify",
                           json={"access_token": "test-fb-token-abc123"})
    assert resp.status_code == 400


async def test_fb_verify_endpoint_503_without_config(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "META_LOGIN_APP_ID", "")
    monkeypatch.setattr(settings, "META_APP_ID", "")
    with patch("app.modules.auth.router.rate_limit",
               new_callable=AsyncMock, return_value=True):
        resp = client.post("/api/v1/auth/facebook/verify",
                           json={"access_token": "test-fb-token-abc123"})
    assert resp.status_code == 503
    assert "META_LOGIN_APP_ID" in resp.json()["detail"]
```

- [ ] **Step 2: Run (expect 4 failed — 404, route missing)**

```powershell
& "D:\code\sayvors\.venv\Scripts\python.exe" -m pytest tests/test_facebook_signin.py -q 2>&1 | Select-Object -Last 6
```

- [ ] **Step 3: Schema** — append to `schemas.py`:

```python
class FacebookVerifyRequest(BaseModel):
    access_token: str = Field(..., min_length=10, max_length=8000)
```

- [ ] **Step 4: Router** — extend the two import blocks
  (`FacebookVerifyRequest` in schemas; `verify_facebook_token` in security import;
  `facebook_login` in service import), then insert after `google_verify_endpoint`
  (before `@router.post("/verify-email")`):

```python
@router.post("/facebook/verify")
async def facebook_verify_endpoint(
    body: FacebookVerifyRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Sign in / sign up / link via a Facebook Login user token.

    The token is verified server-side (debug_token app check + profile fetch);
    Meta's tokens are discarded and only the profile snapshot is stored.
    Session issuance is identical to password/Google login."""
    ip = get_client_ip(request)
    user_agent = request.headers.get("user-agent", "")

    if not await rate_limit(f"facebook:{ip}", 30, 60):
        raise HTTPException(status_code=429, detail="Too many attempts. Try again later.")
    if not settings.facebook_login_app_id:
        raise HTTPException(
            status_code=503,
            detail="Facebook Sign-In not configured. Set META_LOGIN_APP_ID in .env",
        )

    try:
        profile = verify_facebook_token(body.access_token)
    except ValueError as e:
        if str(e) == "unverified_email":
            raise HTTPException(
                status_code=400,
                detail="No verified email on this Facebook account.",
            )
        raise HTTPException(status_code=401, detail="Facebook sign-in failed")

    try:
        result = await facebook_login(profile, db, user_agent, ip)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    refresh_token = result.pop("refresh_token")
    _set_session_cookies(response, refresh_token)
    return result
```

- [ ] **Step 5: CSRF exempt** — in `main.py` `skip_prefixes`, add after the google line:

```python
            "/api/v1/auth/google/verify",
            "/api/v1/auth/facebook/verify",
```

- [ ] **Step 6: Run (expect all pass)**

```powershell
& "D:\code\sayvors\.venv\Scripts\python.exe" -m pytest tests/test_facebook_signin.py -q 2>&1 | Select-Object -Last 2
```

- [ ] **Step 7: Selective commit** — `schemas.py` + `main.py` + test file whole;
  `router.py` via `filter_hunks.py` markers `verify_facebook_token`,
  `FacebookVerifyRequest`, `facebook_login`, `facebook_verify_endpoint`
  (run at `-U1`; user's `UpdateMeRequest` hunks must remain unstaged — verify with
  `git diff -- <file>` showing no `facebook` markers left unstaged):

```powershell
git add services/api/app/modules/auth/schemas.py services/api/app/main.py services/api/tests/test_facebook_signin.py
git commit -m "feat(auth): POST /auth/facebook/verify endpoint"
```

(Amend the router hunks into this commit only after verifying the staged diff.)

---

### Task 6: `facebookLogin` in auth-context

**Files:**
- Modify: `apps/web/lib/auth-context.tsx` (3 edits mirroring `googleLogin`)

- [ ] **Step 1: Type + function + provider value**

```typescript
  facebookLogin: (accessToken: string) => Promise<User>;
```

```typescript
  const facebookLogin = async (accessToken: string): Promise<User> => {
    const res = await apiFetch("/api/v1/auth/facebook/verify", {
      method: "POST",
      body: JSON.stringify({ access_token: accessToken }),
    });

    if (!res.ok) {
      const err = await res.json();
      const detail = (err as any).detail;
      throw new Error(typeof detail === "string" ? detail : "Facebook sign-in failed");
    }

    const result = await res.json();
    if (result.access_token) setAccessToken(result.access_token);
    setUser(result.user);
    return result.user as User;
  };
```

plus `facebookLogin,` in the provider value after `googleLogin,`.

- [ ] **Step 2: Type-check (expect exit 0)**

```powershell
npx tsc --noEmit
```

- [ ] **Step 3: Commit**

```powershell
git add lib/auth-context.tsx
git commit -m "feat(web): facebookLogin in auth context"
```

---

### Task 7: AuthForm Facebook button (delete GitHub stub) + assets + env

**Files:**
- Modify: `apps/web/components/AuthForm.tsx`
- Create: `apps/web/public/facebook.svg`
- Modify: `apps/web/.env.example` (append `NEXT_PUBLIC_META_LOGIN_APP_ID=`)
- Modify: `deploy/env.prod.example` (append same; SELECTIVE-STAGE — user WIP present)
- Verify: CSP headers (no code change expected)

- [ ] **Step 1: `facebook.svg`** — same 18px usage as `google.svg`:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
  <path fill="#1877F2" d="M24 12.073c0-6.627-5.373-12-12-12s-12 5.373-12 12c0 5.99 4.388 10.954 10.125 11.854v-8.385H7.078v-3.47h3.047V9.43c0-3.007 1.792-4.669 4.533-4.669 1.312 0 2.686.235 2.686.235v2.953H15.83c-1.491 0-1.956.925-1.956 1.874v2.25h3.328l-.532 3.47h-2.796v8.385C19.612 23.027 24 18.062 24 12.073z"/>
</svg>
```

- [ ] **Step 2: AuthForm edits**

1. Destructure (line ~175):

```typescript
  const { signup, login, googleLogin, facebookLogin } = useAuth();
```

2. Module scope after imports — API base for the same-origin SDK proxy:

```typescript
const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
```

3. State + loader effect — place after the GIS `useEffect`, before `const pw = useMemo`:

```typescript
  const [fbStatus, setFbStatus] = useState<"loading" | "ready" | "blocked" | "hidden">(() =>
    process.env.NEXT_PUBLIC_META_LOGIN_APP_ID ? "loading" : "hidden"
  );

  useEffect(() => {
    const appId = process.env.NEXT_PUBLIC_META_LOGIN_APP_ID;
    if (!appId) { setFbStatus("hidden"); return; }
    const w = window as any;
    const initFb = () => {
      try {
        w.FB.init({ appId, version: "v26.0", xfbml: false, cookie: false });
        setFbStatus("ready");
      } catch (e) {
        console.error("Facebook SDK init failed:", e);
        setFbStatus("blocked");
      }
    };
    if (w.FB) { initFb(); return; }
    const prevInit = w.fbAsyncInit;
    w.fbAsyncInit = () => { try { prevInit?.(); } catch { /* ignore */ } initFb(); };
    if (document.getElementById("facebook-jssdk-auth")) return;
    const s = document.createElement("script");
    s.id = "facebook-jssdk-auth";
    s.src = `${API_URL}/api/v1/meta/connect-sdk`;
    s.async = true;
    const to = setTimeout(() => setFbStatus("blocked"), 8000);
    const chained = w.fbAsyncInit;
    w.fbAsyncInit = () => { clearTimeout(to); chained(); };
    s.onerror = (e) => {
      clearTimeout(to);
      console.error("Failed to load Meta SDK for Facebook sign-in", e);
      setFbStatus("blocked");
    };
    document.head.appendChild(s);
    // Init once on mount; facebookLogin identity is stable enough for this use.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
```

4. Click handler — place after `back`, before `submit`. NOTE: the `FB.login`
callback MUST be a plain `function` (the SDK rejects async callbacks —
see `MetaConnections.tsx:259`); the async work goes in an inner IIFE:

```typescript
  const continueWithFacebook = () => {
    const w = window as any;
    const onFbLogin = function (resp: { authResponse?: { accessToken?: string } | null }) {
      const token = resp?.authResponse?.accessToken;
      if (!token) { setNote("Facebook sign-in cancelled."); return; }
      (async () => {
        try {
          const u = await facebookLogin(token);
          window.location.href = u?.onboarded ? "/dashboard" : "/onboarding";
        } catch {
          setNote("Facebook sign-in failed. Try again or use your password.");
        }
      })();
    };
    try {
      w.FB.login(onFbLogin, { scope: "email", auth_type: "rerequest" });
    } catch {
      setNote("Facebook couldn't start. Check your ad-blocker, or continue with password.");
    }
  };
```

5. Replace the GitHub stub button with the three states:

```tsx
        {fbStatus === "loading" && (
          <div aria-hidden className="flex h-11 w-full items-center justify-center gap-2.5 rounded-lg border border-ink/[0.12] text-[14px] font-medium text-ink/40">
            <span className="h-4 w-4 animate-spin rounded-full border-2 border-ink/20 border-t-ink/60" />
            Loading Facebook...
          </div>
        )}
        {fbStatus === "ready" && (
          <button type="button" onClick={continueWithFacebook}
            className="flex h-11 w-full items-center justify-center gap-2.5 rounded-lg border border-ink/[0.12] text-[14px] font-medium text-ink/70 transition-all duration-200 hover:border-ink/20 hover:bg-ink/[0.02] active:scale-[0.99]">
            <Image src="/facebook.svg" alt="" width={18} height={18} className="h-[18px] w-[18px]" />
            Continue with Facebook
          </button>
        )}
        {fbStatus === "blocked" && (
          <p className="rounded-lg border border-ink/[0.12] px-3 py-2.5 text-center text-[12px] text-ink/55 animate-in fade-in duration-200">Facebook couldn{"\u2019"}t load — check your ad-blocker, or continue with password below.</p>
        )}
```

6. `Image` import stays (still used by this button). `github.svg` file: leave the
file in `public/` (dead asset, harmless) — deleting public assets is out of scope.

- [ ] **Step 3: Env examples** — append `NEXT_PUBLIC_META_LOGIN_APP_ID=` (+ comment
  `# Facebook Login app id (same value as META_APP_ID for now). Empty hides the button.`)
  to `apps/web/.env.example` and `deploy/env.prod.example` (selective-stage the latter
  with marker `NEXT_PUBLIC_META_LOGIN_APP_ID`).

- [ ] **Step 4: Verify CSP needs no change** — fetch `/login` headers; assert
  `script-src` contains the API host (same-origin proxy), `frame-src` contains
  `facebook.com`, `connect-src` contains `graph.facebook.com`. If any missing, fix
  `middleware.ts` (that would be a plan deviation — report it).

- [ ] **Step 5: Type-check (expect exit 0)**

```powershell
npx tsc --noEmit
```

- [ ] **Step 6: Visual check with Playwright** (`check script` pattern from the Google
  round): load `/login`, assert the Facebook button (text "Continue with Facebook")
  is visible; enable `page.route("**/connect-sdk*", abort)` reload variant or block
  `connect.facebook.net` and assert the blocked warning shows; screenshot both.

- [ ] **Step 7: Commit**

```powershell
git add components/AuthForm.tsx public/facebook.svg .env.example
git commit -m "feat(web): Continue with Facebook button, visible load/blocked states"
```

(deploy hunk via `git apply --cached`, same commit if the staged diff is exactly the added lines.)

---

### Task 8: Full verification

**Files:** none (verification only)

- [ ] **Step 1: Full backend suite** (from `services/api`)

```powershell
& "D:\code\sayvors\.venv\Scripts\python.exe" -m pytest -q 2>&1 | Select-Object -Last 8
```

Expected: all Facebook + Google tests pass; **only** the 4 known pre-existing failures
(`test_admin_health_structure`, `test_overview_empty`,
`test_autoreply_model_restricted_to_admin_enabled`, `test_period_bounds_equal_length`).

- [ ] **Step 2: Frontend type-check** — `npx tsc --noEmit`, expect exit 0.

- [ ] **Step 3: Manual smoke checklist** (Meta app in Dev mode → use a listed test user;
  public use needs App Review for `email`):
  1. `/signup` → Continue with Facebook → consent → `/onboarding` + welcome email received.
  2. Log out → `/login` → Facebook → same account → `/dashboard`.
  3. Password account with email X → log out → Facebook with email X → same user,
     password still works.
  4. Decline email permission → clear "need your email" note, no account created.
  5. Ad-blocker on → blocked warning visible, password flow unaffected.
  6. No `NEXT_PUBLIC_META_LOGIN_APP_ID` → button hidden (skeleton never flashes).

- [ ] **Step 4: Final status review**

```powershell
git status --short
git log --oneline -8
```

Expected: feature commits present; user WIP still uncommitted. **Do not push**
unless the user says "push". Local `services/api/.env` and `apps/web/.env.local`
still need the real `META_LOGIN_APP_ID/SECRET` + `NEXT_PUBLIC_META_LOGIN_APP_ID`
values — that is the user's job (never commit those files).

## Self-review

- Spec coverage: identity rules→T4; endpoint/verify→T3+T5; frontend/states→T6+T7;
  welcome email (+Google retrofit)→T4; GitHub removal→T7; CSP→T7-step-4;
  config fallback→T2; rate/CSRF→T5; tests/manual→T8. Covered.
- Placeholders: none — every step has exact code/commands/expectations.
- Type consistency: profile dict `{id,email,name,picture}` produced in T3,
  consumed in T4/T5 identically; `facebookLogin(token)->User` in T6/T7;
  endpoint user shape matches Google's. Consistent.


