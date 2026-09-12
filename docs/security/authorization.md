# Authorization

## Access Control Model

### Resource-Based Access Control

Sayvors uses **resource-based authorization** where every API endpoint validates:
1. **Authentication** - Valid access token
2. **Ownership** - User owns the resource
3. **Scope** - Token has required permissions (future)

### Ownership Validation Pattern

```python
# Standard pattern in all routers
@router.get("/{resource_id}")
async def get_resource(
    resource_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    resource = await service.get_resource(db, user.id, resource_id)
    if not resource:
        raise HTTPException(404, "Resource not found")
    return resource
```

Service layer enforces ownership:

```python
async def get_resource(db: AsyncSession, user_id: str, resource_id: str):
    # Query with user_id filter - never trust client-provided user_id
    result = await db.execute(
        select(Resource).where(
            Resource.id == resource_id,
            Resource.user_id == user_id  # Ownership check
        )
    )
    return result.scalar_one_or_none()
```

## Resource Types & Permissions

### User Resources

| Resource | Owner Field | Access Pattern |
|----------|-------------|----------------|
| User Profile | `id` | Self only (`/auth/me`) |
| Sessions | `user_id` | Self only (`/auth/sessions`) |
| Locations | `user_id` (via Channel/LocalithConnection) | List/Get/Update own |
| Posts | `user_id` | CRUD own |
| Channels | `user_id` | CRUD own |
| Databanks | `user_id` | CRUD own |
| Conversations | `user_id` | CRUD own |
| Analytics | `user_id` (or demo) | Read own |

### Cross-Resource Access

#### Channels → Reviews/Replies
```python
# Channel ownership verified first
async def _get_owned_channel(channel_id: str, user: User, db: AsyncSession) -> Channel:
    channel = await get_channel(channel_id, user, db)
    if not channel or channel.user_id != user.id:
        raise HTTPException(404, "Channel not found")
    return channel

# Then review operations scoped to channel
@router.get("/{channel_id}/reviews")
async def list_reviews(
    channel_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    channel = await _get_owned_channel(channel_id, user, db)
    # Query reviews for THIS channel only
```

#### Locations → Posts
```python
# Posts require listing_id which maps to user's location
@router.post("/")
async def create_post(
    body: PostCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Service validates user owns the listing_id
    result = await service.create_post(db, user.id, body.model_dump())
```

## Admin Authorization

### Admin Role

```python
# User model
class User(Base):
    ...
    is_admin: Mapped[bool] = mapped_column(default=False)
```

### Admin Endpoints

```python
async def get_current_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(403, "Admin access required")
    return user

@router.get("/admin/users")
async def list_all_users(admin: User = Depends(get_current_admin), ...):
    # No user_id filter - admin sees all
```

### Admin Capabilities
- View all users
- Impersonate users (future)
- System health/metrics
- Configuration management

## Channel-Level Permissions

### Platform-Specific Scopes

| Platform | Permissions Granted |
|----------|---------------------|
| Google Reviews | Read reviews, reply, manage location, insights |
| Facebook | Read messages, send messages, manage page |
| Instagram | Read comments, reply, manage account |
| X (Twitter) | Read tweets, send DMs, manage account |
| WhatsApp | Send messages, manage templates |
| Telegram | Send messages, manage bot |
| LinkedIn | Read messages, send messages |

### Token Storage & Scope

```python
class Channel(Base):
    ...
    access_token: Mapped[str] = mapped_column(encrypted=True)
    refresh_token: Mapped[str | None] = mapped_column(encrypted=True)
    token_expires_at: Mapped[datetime | None]
    scopes: Mapped[str] = mapped_column(default="")  # Space-separated
    webhook_secret: Mapped[str | None]
    metadata_json: Mapped[str]  # Platform-specific data
```

### Token Encryption

```python
# AES-256-GCM with key derived from CHANNEL_ENCRYPTION_KEY (or JWT_SECRET)
def encrypt_token(token: str) -> str:
    key = get_encryption_key()  # 32 bytes
    nonce = secrets.token_bytes(12)
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    ciphertext, tag = cipher.encrypt_and_digest(token.encode())
    return base64.b64encode(nonce + ciphertext + tag).decode()

def decrypt_token(encrypted: str) -> str:
    data = base64.b64decode(encrypted)
    nonce, ciphertext, tag = data[:12], data[12:-16], data[-16:]
    key = get_encryption_key()
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    return cipher.decrypt_and_verify(ciphertext, tag).decode()
```

## Demo Mode Authorization

### Behavior

When `DEMO_MODE=true`:
- Analytics endpoints return demo user's data regardless of authenticated user
- Used for presentations/test-drives
- **Does not affect** write operations or sensitive data

```python
def _resolve_uid(db: AsyncSession, user) -> str:
    if settings.DEMO_MODE:
        return DEMO_USER_ID_FALLBACK  # Static demo user
    return user.id

@router.get("/overview")
async def get_overview(user: User = Depends(get_current_user), ...):
    uid = _resolve_uid(db, user)  # Demo mode override
    return await service.get_overview(db, uid, ...)
```

## Future: Fine-Grained RBAC

### Planned Roles

| Role | Description |
|------|-------------|
| `owner` | Full access to organization resources |
| `admin` | Manage team, settings, billing |
| `manager` | Manage locations, posts, replies |
| `analyst` | Read analytics, export reports |
| `responder` | Reply to reviews/messages only |

### Planned Implementation

```python
# Permission format: "resource:action"
PERMISSIONS = {
    "locations": ["read", "write", "delete"],
    "posts": ["read", "write", "publish", "delete"],
    "reviews": ["read", "reply", "approve"],
    "analytics": ["read", "export"],
    "channels": ["read", "connect", "disconnect"],
    "databanks": ["read", "write", "delete"],
    "team": ["invite", "remove", "manage_roles"],
    "billing": ["read", "manage"],
}

# Token would include permissions claim
{
  "sub": "user-uuid",
  "org_id": "org-uuid",
  "role": "manager",
  "permissions": ["locations:read", "posts:write", "reviews:reply"],
  ...
}
```

## Authorization Testing

### Test Cases

```python
async def test_user_cannot_access_other_user_location(client, user1, user2, location1):
    # User1 creates location
    # User2 tries to access
    response = await client.get(
        f"/api/v1/locations/{location1.id}",
        headers=auth_headers(user2)
    )
    assert response.status_code == 404  # Not found (not 403 to avoid enumeration)

async def test_user_cannot_delete_other_user_post(client, user1, user2, post1):
    response = await client.delete(
        f"/api/v1/posts/{post1.id}",
        headers=auth_headers(user2)
    )
    assert response.status_code == 404

async def test_admin_can_access_all_users(admin_client):
    response = await admin_client.get("/api/v1/admin/users")
    assert response.status_code == 200
    assert len(response.json()) > 1

async def test_channel_isolation(client, user1, user2, channel1):
    # User2 cannot access user1's channel reviews
    response = await client.get(
        f"/api/v1/channels/{channel1.id}/reviews",
        headers=auth_headers(user2)
    )
    assert response.status_code == 404
```

## Authorization Checklist

- [ ] All GET endpoints filter by `user_id`
- [ ] All PUT/PATCH/DELETE endpoints verify ownership
- [ ] Channel operations verify channel ownership first
- [ ] Location operations verify location ownership
- [ ] Post operations verify listing ownership
- [ ] Analytics respects demo mode but not for writes
- [ ] Admin endpoints require `is_admin` flag
- [ ] No direct object references without ownership check
- [ ] Error messages don't leak resource existence (404 vs 403)
- [ ] Token scopes validated for external API calls