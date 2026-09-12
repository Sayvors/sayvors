# Secure Development Practices

## Current State

**No formal secure SDLC exists.** Practices are ad-hoc and inconsistent.

## Code Review

### Current
- No required reviews
- No security-focused review checklist
- No automated security gates in PR pipeline

### Recommended Minimum
```yaml
# Branch protection rules
required_reviews: 1
require_code_owner_review: true
required_status_checks:
  - "lint"
  - "typecheck"
  - "test"
  - "security-scan"  # New
dismiss_stale_reviews: true
```

### Security Review Checklist (Not Enforced)

- [ ] No secrets in diff
- [ ] Input validation on all new endpoints
- [ ] Ownership checks on all resource access
- [ ] Rate limiting on new public endpoints
- [ ] CSRF protection on state-changing endpoints
- [ ] Error messages don't leak information
- [ ] Logging doesn't include sensitive data
- [ ] Dependencies reviewed for new packages
- [ ] Database migrations reviewed for data loss

## Development Environment

### Current
- Local `.env` files (gitignored)
- No pre-commit hooks enforced
- No local secret scanning

### Recommended
```bash
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.5.0
    hooks:
      - id: detect-secrets
      - id: check-added-large-files
      - id: check-merge-conflict
      - id: debug-logger-statements
      - id: end-of-file-fixer
      - id: trailing-whitespace

  - repo: https://github.com/pycqa/bandit
    rev: 1.7.5
    hooks:
      - id: bandit
        args: ["-r", "services/api/app/"]

  - repo: https://github.com/pycqa/flake8
    rev: 7.0.0
    hooks:
      - id: flake8
```

## Coding Standards (What Exists vs What's Needed)

### Authentication/Authorization
| Practice | Status |
|----------|--------|
| Use `get_current_user` dependency | ✅ Enforced by pattern |
| Ownership checks in service layer | ✅ Mostly consistent |
| Rate limiting on auth endpoints | ✅ Implemented |
| CSRF on mutating endpoints | ✅ Implemented |

### Input Validation
| Practice | Status |
|----------|--------|
| Pydantic models for all inputs | ✅ Consistent |
| Extra fields forbidden | ❌ Not enforced |
| HTML sanitization | ❌ Not implemented |
| File upload validation | ⚠️ Partial (size only) |

### Secrets Handling
| Practice | Status |
|----------|--------|
| No secrets in code | ✅ Generally followed |
| Environment variables for config | ✅ Standard |
| Secret scanning in CI | ❌ Not configured |
| Key rotation documented | ❌ Not documented |

### Logging
| Practice | Status |
|----------|--------|
| Structured JSON logging | ✅ Implemented |
| Request ID correlation | ⚠️ Partial |
| No sensitive data in logs | ✅ Generally followed |
| Audit logging for auth events | ✅ Implemented |

### Error Handling
| Practice | Status |
|----------|--------|
| Generic error messages | ✅ Mostly |
| No stack traces in production | ✅ Via config |
| Proper HTTP status codes | ✅ Consistent |

## Testing

### Current Security Testing
- Unit tests for auth flows
- Some integration tests
- No security-specific test suite
- No fuzzing
- No dependency confusion tests

### Recommended Additions
```python
# tests/security/test_auth_security.py
async def test_rate_limit_enforced(client):
    for _ in range(10):
        await client.post("/api/v1/auth/login", json={...})
    response = await client.post("/api/v1/auth/login", json={...})
    assert response.status_code == 429

async def test_csrf_required_on_mutating(client, auth_headers):
    response = await client.post("/api/v1/posts/", headers=auth_headers, json={...})
    assert response.status_code == 403  # No CSRF

async def test_idor_prevented(client, user1, user2, post1):
    response = await client.get(f"/api/v1/posts/{post1.id}", headers=auth_headers(user2))
    assert response.status_code == 404

async def test_no_password_in_logs(caplog):
    await client.post("/api/v1/auth/login", json={"email": "x", "password": "secret"})
    assert "secret" not in caplog.text
```

## Dependency Management

### Current
- `pyproject.toml` with loose version constraints
- `uv.lock` for reproducible builds
- No automated updates
- No license scanning

### Recommended
```toml
# pyproject.toml
[tool.uv]
dev-dependencies = [
  "bandit>=1.7.5",
  "detect-secrets>=1.5.0",
  "pip-audit>=2.7.0",
  "safety>=3.0.0",
]

[tool.pip-audit]
# Fail on vulnerabilities
fail-on-vuln = true
```

## CI/CD Security

### Current Pipeline (If Exists)
- Basic lint/test
- No security gates
- No image signing
- No deployment attestation

### Recommended Pipeline
```yaml
# .github/workflows/ci.yml
jobs:
  security:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Security scan
        run: |
          pip-audit --fail-on-vuln
          bandit -r services/api/app/ -ll
          detect-secrets scan --baseline .secrets.baseline
      - name: Build image
        run: docker build -t sayvors-api:${{ github.sha }} .
      - name: Scan image
        run: trivy image --severity HIGH,CRITICAL --exit-code 1 sayvors-api:${{ github.sha }}
      - name: Sign image
        run: cosign sign sayvors-api:${{ github.sha }}
      - name: Upload attestation
        run: cosign attest --predicate=build.json sayvors-api:${{ github.sha }}

  deploy-staging:
    needs: security
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    steps:
      - name: Verify image signature
        run: cosign verify sayvors-api:${{ github.sha }}
      - name: Deploy to staging
        run: # Deploy

  deploy-prod:
    needs: deploy-staging
    if: github.event_name == 'release'
    runs-on: ubuntu-latest
    environment: production
    steps:
      - name: Verify image signature
        run: cosign verify sayvors-api:${{ github.sha }}
      - name: Deploy to production
        run: # Deploy
```

## Developer Training (Not Existing)

### Recommended Topics
1. OWASP Top 10 (annual refresher)
2. JWT security best practices
3. Secure code review
4. Threat modeling basics
5. Incident response basics
6. Secrets management

### Frequency
- Onboarding: Required
- Annual: Refresher
- Post-incident: Targeted

## Tooling Inventory

| Tool | Purpose | Status |
|------|---------|--------|
| `bandit` | Python SAST | Available, not in CI |
| `pip-audit` | Dependency vuln scan | Available, not in CI |
| `detect-secrets` | Secret detection | Available, not in CI |
| `trivy` | Container scanning | Available, not in CI |
| `safety` | Dependency scanning | Not used |
| `semgrep` | SAST rules | Not used |
| `dependabot` | Auto-updates | Not configured |
| `renovate` | Auto-updates | Not configured |
| `cosign` | Image signing | Not used |
| `syft` | SBOM generation | Not used |

## Secure Defaults Checklist

### API Endpoints (Enforce via Linter/Review)
- [ ] All endpoints use Pydantic models
- [ ] All mutating endpoints require CSRF
- [ ] All resource endpoints filter by owner
- [ ] All public endpoints have rate limits
- [ ] All errors use generic messages
- [ ] All logs exclude sensitive fields

### Database
- [ ] Parameterized queries only (SQLAlchemy ORM)
- [ ] No dynamic SQL with user input
- [ ] Migrations reviewed for data loss
- [ ] RLS policies for multi-tenant (future)

### Containers
- [ ] Non-root user
- [ ] Read-only rootfs
- [ ] Dropped capabilities
- [ ] No privileged containers
- [ ] Resource limits set
- [ ] Health checks defined

### Kubernetes
- [ ] Network policies
- [ ] Pod security standards (restricted)
- [ ] Resource quotas
- [ ] Limit ranges
- [ ] Secrets via External Secrets Operator

## Documentation Gaps

| Document | Status |
|----------|--------|
| Threat model | Missing |
| Data flow diagram | Missing |
| Security architecture | Partial (this doc) |
| Incident response runbooks | Missing |
| Secure coding guide | This doc |
| Dependency policy | Missing |
| Secret rotation procedure | Missing |