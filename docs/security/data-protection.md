# Data Protection

## Data Classification

| Classification | Examples | Protection |
|----------------|----------|------------|
| **Critical** | Passwords, JWT secrets, API keys, encryption keys | Encrypted at rest, never logged, rotation |
| **High** | Access/refresh tokens, PII (email, name), business data | Encrypted at rest, TLS in transit, access control |
| **Medium** | Analytics, reviews, posts, location data | Access control, TLS in transit |
| **Low** | Public business info, aggregated metrics | Standard access control |

## Encryption

### In Transit

- **TLS 1.2+** enforced everywhere
- **HSTS** with 1-year max-age
- **Certificate pinning** for external APIs (planned)
- **mTLS** for service-to-service (planned)

### At Rest

#### Database (PostgreSQL)

```sql
-- Column-level encryption for sensitive fields
-- Using pgcrypto or application-level encryption

-- Channel tokens (AES-256-GCM)
access_token BYTEA  -- Encrypted
refresh_token BYTEA -- Encrypted
webhook_secret BYTEA -- Encrypted

-- Encryption key from CHANNEL_ENCRYPTION_KEY env var
-- Falls back to JWT_SECRET if not set
```

#### Application-Level Encryption

```python
# AES-256-GCM for channel tokens
def get_encryption_key() -> bytes:
    key = settings.CHANNEL_ENCRYPTION_KEY or settings.JWT_SECRET
    # Derive 32-byte key
    return hashlib.sha256(key.encode()).digest()

def encrypt_token(token: str) -> str:
    key = get_encryption_key()
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

#### File Storage

- Uploads stored in `./data/uploads/` (local) or S3 (production)
- **S3**: Server-side encryption (SSE-S3 or SSE-KMS)
- **Local**: Disk encryption (LUKS) recommended
- Max file size: 100MB (configurable)

### Key Management

| Key | Purpose | Rotation |
|-----|---------|----------|
| `JWT_SECRET` | JWT signing | 90 days |
| `CHANNEL_ENCRYPTION_KEY` | Channel token encryption | 90 days |
| Database encryption | TDE (if enabled) | Cloud provider managed |
| TLS certificates | HTTPS | 90 days (Let's Encrypt) |

### Key Derivation

```python
# For encryption keys from passphrase
def derive_key(passphrase: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac('sha256', passphrase.encode(), salt, 100000, dklen=32)
```

## PII Handling

### Collected PII

| Data | Source | Retention | Legal Basis |
|------|--------|-----------|-------------|
| Email | Signup | Account lifetime | Contract |
| Name | Signup | Account lifetime | Contract |
| IP Address | Request metadata | 30 days (login_attempts) | Legitimate interest |
| User Agent | Request metadata | 30 days | Legitimate interest |
| Location (business) | Google/EmbedSocial | Account lifetime | Contract |
| Reviews (customer) | Platform APIs | 2 years | Legitimate interest |

### Data Minimization

- Only collect required fields
- No SSN, payment info, health data
- Optional fields clearly marked
- Analytics uses aggregated/anonymized data

### Right to Deletion (GDPR Art. 17)

```python
async def delete_user_data(user_id: str, db: AsyncSession):
    # 1. Revoke all tokens (blacklist)
    # 2. Delete refresh tokens
    # 3. Delete login attempts
    # 4. Anonymize or delete:
    #    - User profile (email, name)
    #    - Locations (user's business data)
    #    - Posts
    #    - Channels (revoke platform tokens first)
    #    - Databanks
    #    - Conversations
    #    - Analytics data (or anonymize)
    # 5. Delete user record
    # 6. Audit log deletion event
```

### Data Export (GDPR Art. 20)

```python
async def export_user_data(user_id: str, db: AsyncSession) -> dict:
    return {
        "profile": await get_user_profile(user_id, db),
        "locations": await get_user_locations(user_id, db),
        "posts": await get_user_posts(user_id, db),
        "channels": await get_user_channels(user_id, db),
        "databanks": await get_user_databanks(user_id, db),
        "conversations": await get_user_conversations(user_id, db),
        "analytics_summary": await get_analytics_summary(user_id, db),
    }
```

## Secrets Management

### Environment Variables

```bash
# Required secrets (never commit)
JWT_SECRET=                        # 64+ char random
CHANNEL_ENCRYPTION_KEY=            # 32+ char random
DATABASE_URL=postgresql+asyncpg://...
REDIS_URL=redis://...
KAFKA_BOOTSTRAP_SERVERS=...

# External API keys
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
RESEND_API_KEY=
OPENAI_API_KEY=
XAI_API_KEY=
GROQ_API_KEY=
GEMINI_API_KEY=
LOCALITH_API_KEY=
```

### Secret Handling Rules

1. **Never** commit secrets to git
2. **Never** log secrets (use `***` in logs)
3. **Never** put secrets in URLs
4. Use `.env` files (gitignored) for local dev
5. Use secret manager (AWS Secrets Manager, HashiCorp Vault) in production
6. Rotate secrets every 90 days
7. Revoke compromised secrets immediately

### Secret Scanning

```bash
# Pre-commit hook
pip install detect-secrets
detect-secrets scan --baseline .secrets.baseline

# CI pipeline
- name: Secret Scan
  run: detect-secrets scan
```

## Logging & Auditing

### Structured Logging (JSON)

```python
import logging
import json

class JsonFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", None),
            "user_id": getattr(record, "user_id", None),
            "ip": getattr(record, "ip", None),
        })
```

### What to Log

| Event | Fields |
|-------|--------|
| Login success | user_id, ip, user_agent, request_id |
| Login failure | email (hash), ip, reason, request_id |
| Token refresh | user_id, request_id |
| Password change | user_id, request_id |
| Email verification | user_id, request_id |
| Channel connect | user_id, platform, channel_id, request_id |
| Channel disconnect | user_id, channel_id, request_id |
| Post publish | user_id, post_id, channel_id, request_id |
| Review reply | user_id, channel_id, review_id, request_id |
| Admin action | admin_id, action, target, request_id |
| Error | error_code, message, stack_trace (dev), request_id |

### What NOT to Log

- ❌ Passwords
- ❌ Tokens (access, refresh, reset, verify)
- ❌ API keys (Google, OpenAI, etc.)
- ❌ Encryption keys
- ❌ Full credit card numbers
- ❌ SSN, health data
- ❌ Webhook signatures

### Log Retention

| Log Type | Retention |
|----------|-----------|
| Application logs | 30 days |
| Audit logs | 1 year |
| Security events | 2 years |
| Access logs (nginx) | 90 days |

## Data Retention

### Automated Cleanup

```python
# Retention job runs every 6 hours (configurable)
RETENTION_CLEANUP_INTERVAL_SECONDS = 6 * 3600
RETENTION_DELETE_BATCH_SIZE = 1000

async def cleanup_expired_data(db: AsyncSession):
    # login_attempts older than 30 days
    # refresh_tokens older than 30 days (revoked)
    # verification_tokens expired
    # password_reset_tokens expired
    # outbox events processed > 7 days
```

### Retention Periods

| Data | Retention | Reason |
|------|-----------|--------|
| Login attempts | 30 days | Security audit |
| Refresh tokens (revoked) | 30 days | Forensics |
| Email verification tokens | 24 hours | Expiry |
| Password reset tokens | 1 hour | Expiry |
| Outbox events | 7 days | Replay |
| Analytics daily metrics | 2 years | Business |
| Reviews (enriched) | 2 years | Business |
| User data | Account lifetime | Contract |
| Audit logs | 2 years | Compliance |

## Backup & Recovery

### Database Backups

- **Frequency**: Daily (automated)
- **Retention**: 30 days
- **Encryption**: AES-256 (cloud provider)
- **Test Restore**: Monthly

### Point-in-Time Recovery

- WAL archiving enabled
- RPO: < 5 minutes
- RTO: < 1 hour

### Disaster Recovery

- Multi-AZ deployment
- Cross-region backup replication
- Runbook documented
- Quarterly DR test

## Third-Party Data Processing

### Data Processors

| Processor | Purpose | DPA | Location |
|-----------|---------|-----|----------|
| Google | Business Profile API | Yes | Global |
| EmbedSocial (Localith) | Reviews/locations sync | Yes | EU/US |
| Resend | Transactional email | Yes | US |
| Groq/OpenAI/Gemini | LLM inference | Yes | US |
| Redis Cloud | Caching/rate limiting | Yes | Global |
| Kafka (Confluent/self-hosted) | Event streaming | Yes | Global |

### Data Processing Agreements

- All processors have signed DPAs
- SCCs for international transfers
- Sub-processor lists maintained

## Security Testing

### Automated Scans

```bash
# Dependency scanning
pip-audit --desc

# SAST
bandit -r services/api/app/

# Secrets
detect-secrets scan

# Container
trivy image sayvors-api:latest
```

### Penetration Testing

- Annual third-party pen test
- Scope: API, web app, infrastructure
- Remediation SLA: Critical 7d, High 30d, Medium 90d

## Compliance Checklist

### GDPR
- [ ] Lawful basis documented
- [ ] Data minimization implemented
- [ ] Right to access (export)
- [ ] Right to deletion
- [ ] Right to portability
- [ ] DPIA for high-risk processing
- [ ] DPA with all processors
- [ ] Breach notification procedure (72h)

### SOC 2 (Target)
- [ ] Access controls (CC6.1)
- [ ] Encryption (CC6.7)
- [ ] Audit logging (CC7.2)
- [ ] Incident response (CC7.4)
- [ ] Vulnerability management (CC7.5)
- [ ] Change management (CC8.1)

## Data Protection Checklist

- [ ] TLS 1.2+ enforced everywhere
- [ ] Channel tokens encrypted at rest (AES-256-GCM)
- [ ] Passwords hashed with bcrypt cost 12
- [ ] JWT secrets rotated quarterly
- [ ] No secrets in logs or git
- [ ] PII minimized and documented
- [ ] Deletion/export procedures implemented
- [ ] Retention policies enforced
- [ ] Backups encrypted and tested
- [ ] Third-party DPAs in place
- [ ] Automated secret scanning in CI
- [ ] Dependency scanning in CI