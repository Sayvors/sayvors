# Security Overview

## Security Principles

### Defense in Depth
Multiple layers of security controls:
1. **Network** - VPC, security groups, WAF
2. **Application** - AuthZ, input validation, CSRF
3. **Data** - Encryption at rest/in transit, tokenization
4. **Operations** - Monitoring, logging, incident response

### Zero Trust
- Never trust, always verify
- All requests authenticated and authorized
- Least privilege access
- Continuous validation

### Secure by Default
- Secure configurations out of the box
- Fail-closed on security decisions
- Explicit opt-in for reduced security (dev only)

## Threat Model

### Assets
| Asset | Classification | Protection |
|-------|----------------|------------|
| User credentials | Critical | bcrypt, JWT, HTTP-only cookies |
| Access/refresh tokens | Critical | Rotation, short TTL, secure storage |
| PII (email, name) | High | Encryption at rest, minimal collection |
| Business data (reviews, locations) | High | RBAC, encryption |
| API keys (Google, LLM providers) | Critical | Encrypted storage, rotation |
| Analytics/insights | Medium | Access controls |

### Threat Actors
| Actor | Motivation | Capability |
|-------|------------|------------|
| External attacker | Data theft, disruption | Network, application attacks |
| Malicious insider | Data exfiltration | Legitimate access abuse |
| Compromised account | Lateral movement | Valid credentials |
| Supply chain | Code injection | Dependency compromise |

### Attack Vectors & Mitigations

| Vector | Mitigation |
|--------|------------|
| Credential stuffing | Rate limiting, lockout, MFA (planned) |
| Token theft | HTTP-only cookies, short TTL, rotation |
| CSRF | Double-submit cookie, SameSite=Lax |
| XSS | CSP, HttpOnly cookies, output encoding |
| SQL Injection | Parameterized queries (SQLAlchemy ORM) |
| IDOR | Ownership checks on all resources |
| Rate limit bypass | Trusted proxy validation, Redis-backed |
| Webhook spoofing | HMAC signature verification |
| Secret leakage | Env vars, encrypted storage, rotation |

## Security Architecture

```
┌─────────────────────────────────────────────────────────────┐
                        INTERNET                                
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
                      WAF / CDN                                
                  (Rate limit, DDoS, Bot)                     
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
                    API GATEWAY (nginx)                       
              (TLS termination, CORS, Headers)               
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
                     SAYVORS API (FastAPI)                    
┌─────────────┬─────────────┬─────────────┬─────────────────┐
│   Auth      │  Rate Limit │   CSRF      │   Validation    │
│   (JWT)     │  (Redis)    │  (Double)   │  (Pydantic)     │
└─────────────┴─────────────┴─────────────┴─────────────────┘
                              │
          ┌───────────────────┼───────────────────┐
          ▼                   ▼                   ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│  PostgreSQL     │ │     Redis       │ │     Kafka       │
│  (Encrypted)    │ │  (Rate limit,   │ │  (Event stream) │
│                 │ │   sessions)     │ │                 │
└─────────────────┘ └─────────────────┘ └─────────────────┘
```

## Compliance & Standards

### Current Alignment
- **OWASP Top 10** - Addressed in code practices
- **OWASP ASVS** - Level 2 target
- **GDPR** - Data minimization, right to deletion
- **SOC 2 Type II** - Target for production

### Certifications (Planned)
- SOC 2 Type II
- ISO 27001

## Security Controls Summary

### Authentication
- ✅ bcrypt (cost 12) for passwords
- ✅ JWT RS256/HS256 with short TTL (15m)
- ✅ Refresh token rotation
- ✅ HTTP-only, Secure, SameSite cookies
- ✅ CSRF double-submit cookie
- ✅ Account lockout (5 attempts, 15min)
- 🔄 MFA (planned)
- 🔄 Passkeys (planned)

### Authorization
- ✅ Resource ownership validation
- ✅ Channel-level permissions
- ✅ Admin role separation
- 🔄 Fine-grained RBAC (planned)

### Data Protection
- ✅ TLS 1.2+ everywhere
- ✅ AES-256-GCM for channel tokens
- ✅ Field-level encryption for secrets
- ✅ PII minimization
- 🔄 Database encryption at rest (planned)

### API Security
- ✅ Rate limiting (Redis-backed)
- ✅ Input validation (Pydantic)
- ✅ Output encoding
- ✅ Security headers (CSP, HSTS, etc.)
- ✅ Request size limits
- ✅ Trusted proxy IP validation

### Infrastructure
- ✅ Non-root containers
- ✅ Read-only root filesystem
- ✅ Secrets in environment variables
- ✅ Dependency scanning (pip-audit)
- 🔄 Image signing (planned)
- 🔄 Runtime security (planned)

### Monitoring & Response
- ✅ Structured logging (JSON)
- ✅ Audit logs for auth events
- ✅ Error tracking (Sentry)
- 🔄 SIEM integration (planned)
- 🔄 Automated incident response (planned)

## Risk Register

| Risk | Likelihood | Impact | Status |
|------|------------|--------|--------|
| Token theft via XSS | Medium | High | Mitigated (HttpOnly, CSP) |
| Credential stuffing | High | Medium | Mitigated (Rate limit, lockout) |
| CSRF on state changes | Low | High | Mitigated (Double-submit) |
| IDOR on resources | Medium | High | Mitigated (Ownership checks) |
| Webhook spoofing | Low | High | Mitigated (HMAC verification) |
| Secret leakage in logs | Medium | High | Mitigated (Structured logging) |
| Dependency vulnerability | High | Medium | Monitoring (pip-audit) |
| SQL injection | Low | Critical | Mitigated (ORM) |
| DoS via large payloads | Medium | Medium | Mitigated (Size limits) |
| Insider data access | Low | High | Monitoring (Audit logs) |

## Security Contacts

- **Security Team**: security@sayvors.com
- **Bug Bounty**: https://sayvors.com/security (planned)
- **PGP Key**: Available on request

## Related Documents

- [Authentication](authentication.md)
- [Authorization](authorization.md)
- [Data Protection](data-protection.md)
- [API Security](api-security.md)
- [Infrastructure Security](infrastructure.md)
- [Incident Response](incident-response.md)