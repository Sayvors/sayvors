# Incident Response

## Current State

**No formal incident response plan exists.** This document describes what *should* exist based on current infrastructure.

## Incident Classification

| Severity | Criteria | Response Time |
|----------|----------|---------------|
| SEV-1 (Critical) | Data breach, full outage, active exploitation | 15 min |
| SEV-2 (High) | Partial outage, auth bypass, PII exposure | 1 hour |
| SEV-3 (Medium) | Degraded performance, non-critical bug | 4 hours |
| SEV-4 (Low) | Minor issue, cosmetic bug | Next sprint |

## Current Detection Capabilities

### What Exists
- Structured JSON logging (application)
- Error tracking via Sentry (if configured)
- Basic health endpoint (`/health`)
- Database connection pooling monitoring

### What's Missing
- Centralized log aggregation (ELK/Loki)
- Security-specific alerting
- SIEM integration
- Automated anomaly detection
- Audit log retention > 30 days

## Response Procedures (Not Implemented)

### SEV-1: Data Breach
```
1. Detect/Report → 2. Confirm → 3. Contain → 4. Investigate → 5. Notify → 6. Recover → 7. Postmortem
```

**Containment Actions Needed:**
- Revoke all JWT secrets (force re-login)
- Rotate all API keys
- Isolate affected containers
- Enable read-only mode on database
- Preserve logs (S3 Object Lock)

### SEV-2: Auth Bypass
```
1. Disable affected endpoint
2. Rotate JWT_SECRET
3. Invalidate all refresh tokens
4. Deploy patch
5. Force password reset for affected users
```

## Current Gaps

| Gap | Risk | Effort to Fix |
|-----|------|---------------|
| No centralized logging | Cannot correlate events | Medium |
| No alerting on auth anomalies | Late detection | Low |
| No forensic readiness | Cannot investigate | Medium |
| No runbooks | Inconsistent response | Low |
| No tabletop exercises | Untested procedures | Low |
| No breach notification process | Legal compliance risk | Medium |

## Minimal Viable Incident Response (Recommended First Steps)

1. **Enable CloudWatch/ELK** for log aggregation
2. **Add alerts** for: failed login spikes, 401/403 rates, rate limit saturation
3. **Document runbooks** for top 5 scenarios
4. **Test JWT secret rotation** procedure
5. **Establish communication channels** (Slack, PagerDuty)
6. **Define escalation contacts**

## Forensics Readiness Checklist

- [ ] Immutable log storage (S3 Object Lock / Loki retention)
- [ ] Database audit logging (pgaudit) enabled
- [ ] Container image digests recorded per deploy
- [ ] Network flow logs (VPC Flow Logs)
- [ ] API Gateway access logs
- [ ] Secret access logs (CloudTrail / Audit logs)
- [ ] Deploy metadata (commit SHA, author, time) in labels

## Communication Templates (Not Created)

- Internal incident declaration
- Customer notification (if data affected)
- Regulatory notification (72h GDPR)
- Status page updates
- Postmortem template

## Post-Incident Process (Not Defined)

1. Blameless postmortem within 5 business days
2. Root cause analysis (5 Whys)
3. Action items with owners and due dates
4. Follow-up review at 30 days