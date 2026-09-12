# Infrastructure Security

## Network Architecture

```
┌─────────────────────────────────────────────────────────────────┐
                         PUBLIC INTERNET                            
└─────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────┐
                        CLOUDFLARE / WAF                          
                    (DDoS, Bot, Rate Limit, TLS)                 
└─────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────┐
                      VPC (10.0.0.0/16)                           
┌─────────────────────┐ ┌─────────────────────┐ ┌───────────────┐
│   PUBLIC SUBNETS    │ │   PRIVATE SUBNETS   │ │  DATABASE     │
│   (10.0.1.0/24,     │ │   (10.0.10.0/24,    │ │  SUBNETS      │
│    10.0.2.0/24)     │ │    10.0.11.0/24)    │ │  (10.0.20.0/24,│
│                     │ │                     │ │   10.0.21.0/24)│
│  - ALB/Nginx        │ │  - API Containers   │ │               │
│  - NAT Gateway      │ │  - Redis            │ │  - PostgreSQL │
│                     │ │  - Kafka            │ │  - Read Replica│
└─────────────────────┘ └─────────────────────┘ └───────────────┘
```

### Security Groups

| Resource | Inbound | Outbound |
|----------|---------|----------|
| ALB/Nginx | 443 (HTTPS) from 0.0.0.0/0 | 8000 → API containers |
| API Containers | 8000 from ALB SG | 5432 → DB SG, 6379 → Redis SG, 9092 → Kafka SG, 443 → External APIs |
| PostgreSQL | 5432 from API SG | None |
| Redis | 6379 from API SG | None |
| Kafka | 9092 from API SG | None |
| NAT Gateway | None | 0.0.0.0/0 (for external API calls) |

### Network Policies (Kubernetes)

```yaml
# NetworkPolicy for API pods
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: api-network-policy
spec:
  podSelector:
    matchLabels:
      app: sayvors-api
  policyTypes:
  - Ingress
  - Egress
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          name: ingress-nginx
    ports:
    - protocol: TCP
      port: 8000
  egress:
  - to:
    - podSelector:
        matchLabels:
          app: postgresql
    ports:
    - protocol: TCP
      port: 5432
  - to:
    - podSelector:
        matchLabels:
          app: redis
    ports:
    - protocol: TCP
      port: 6379
  - to:
    - namespaceSelector: {}  # External (DNS, APIs)
    ports:
    - protocol: TCP
      port: 443
    - protocol: TCP
      port: 53
    - protocol: UDP
      port: 53
```

## Container Security

### Base Images

```dockerfile
# Use distroless or minimal base
FROM python:3.12-slim AS builder
# ... build dependencies

FROM gcr.io/distroless/python3-debian12:nonroot
COPY --from=builder /app /app
USER nonroot:nonroot
```

### Container Hardening

| Control | Implementation |
|---------|----------------|
| Non-root user | `USER nonroot:nonroot` |
| Read-only rootfs | `readOnlyRootFilesystem: true` |
| Drop capabilities | `capabilities: { drop: ["ALL"] }` |
| No privilege escalation | `allowPrivilegeEscalation: false` |
| Seccomp profile | `RuntimeDefault` |
| Resource limits | CPU/memory requests & limits |

### Kubernetes Pod Security Standards

```yaml
# Restricted profile
apiVersion: policy/v1
kind: PodSecurityPolicy
metadata:
  name: restricted
spec:
  privileged: false
  allowPrivilegeEscalation: false
  requiredDropCapabilities:
  - ALL
  volumes:
  - configMap
  - secret
  - emptyDir
  - projected
  - downwardAPI
  - persistentVolumeClaim
  runAsUser:
    rule: MustRunAsNonRoot
  seLinux:
    rule: RunAsAny
  fsGroup:
    rule: RunAsAny
```

### Image Scanning

```bash
# CI Pipeline
- name: Build
  run: docker build -t sayvors-api:$SHA .

- name: Scan
  run: |
    trivy image --severity HIGH,CRITICAL sayvors-api:$SHA
    grype sayvors-api:$SHA

- name: Sign
  run: cosign sign sayvors-api:$SHA
```

### Runtime Security (Planned)

- Falco for runtime threat detection
- eBPF-based syscall monitoring
- Admission controllers (Kyverno/OPA)

## Secrets Management

### Development

```bash
# .env file (gitignored)
JWT_SECRET=local-dev-secret-change-in-production
CHANNEL_ENCRYPTION_KEY=local-dev-encryption-key-32chars
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/sayvors
REDIS_URL=redis://localhost:6379/0
```

### Production (AWS Secrets Manager)

```json
{
  "JWT_SECRET": "***",
  "CHANNEL_ENCRYPTION_KEY": "***",
  "DATABASE_URL": "postgresql+asyncpg://user:***@db-host:5432/sayvors",
  "REDIS_URL": "rediss://:***@redis-host:6379/0",
  "KAFKA_BOOTSTRAP_SERVERS": "kafka-host:9092",
  "GOOGLE_CLIENT_SECRET": "***",
  "RESEND_API_KEY": "***",
  "GROQ_API_KEY": "***",
  "OPENAI_API_KEY": "***"
}
```

### Secret Injection

```yaml
# Kubernetes External Secrets Operator
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: sayvors-secrets
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: aws-secretsmanager
    kind: ClusterSecretStore
  target:
    name: sayvors-env
    creationPolicy: Owner
  dataFrom:
  - extract:
      key: sayvors/production
```

### Secret Rotation

```bash
# Automated rotation (90 days)
# 1. Generate new secret
# 2. Update in Secrets Manager
# 3. Rollout deployment (rolling update)
# 4. Verify health
# 5. Revoke old secret

# JWT_SECRET rotation requires:
# - New secret in SM
# - Deploy with new secret
# - All existing tokens invalidated (force re-login)
# - Communicate to users if needed
```

## Database Security

### PostgreSQL Hardening

```sql
-- Enable SSL
ssl = on
ssl_cert_file = 'server.crt'
ssl_key_file = 'server.key'
ssl_ca_file = 'root.crt'

-- Connection limits
max_connections = 200
superuser_reserved_connections = 3

-- Logging
log_connections = on
log_disconnections = on
log_duration = on
log_statement = 'ddl'
log_min_duration_statement = 1000

-- Row Level Security (future)
-- ALTER TABLE users ENABLE ROW LEVEL SECURITY;
-- CREATE POLICY user_isolation ON users FOR ALL TO app_user USING (id = current_user_id());
```

### Encryption

- **In Transit**: TLS 1.2+ (enforced)
- **At Rest**: 
  - Cloud: AWS RDS encryption (KMS)
  - Self-hosted: LUKS disk encryption
- **Column-level**: Application-level for tokens (AES-256-GCM)

### Access Control

```sql
-- Application user (least privilege)
CREATE ROLE sayvors_app WITH LOGIN PASSWORD '***';
GRANT CONNECT ON DATABASE sayvors TO sayvors_app;
GRANT USAGE ON SCHEMA public TO sayvors_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO sayvors_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO sayvors_app;

-- Read-only for analytics
CREATE ROLE sayvors_readonly WITH LOGIN PASSWORD '***';
GRANT CONNECT ON DATABASE sayvors TO sayvors_readonly;
GRANT USAGE ON SCHEMA public TO sayvors_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO sayvors_readonly;
```

### Auditing

```sql
-- pgaudit extension
CREATE EXTENSION pgaudit;

-- Log all DDL and DML by app user
SET pgaudit.log = 'write, ddl';
SET pgaudit.log_level = 'log';
SET pgaudit.log_parameter = on;
```

## Redis Security

### Configuration

```conf
# redis.conf
bind 127.0.0.1  # Or private subnet only
port 6379
tls-port 6380
tls-cert-file /etc/redis/tls/redis.crt
tls-key-file /etc/redis/tls/redis.key
tls-ca-cert-file /etc/redis/tls/ca.crt
tls-auth-clients yes

requirepass ***  # Strong password
rename-command FLUSHDB ""
rename-command FLUSHALL ""
rename-command KEYS ""
rename-command CONFIG ""
rename-command SHUTDOWN ""
rename-command DEBUG ""

maxmemory 2gb
maxmemory-policy allkeys-lru

# Persistence
appendonly yes
appendfsync everysec
```

### Access Control

```bash
# ACL users (Redis 6+)
ACL SETUSER sayvors_app on >password ~* +@all -@dangerous
ACL SETUSER sayvors_readonly on >password ~* +@read
```

## Kafka Security

### SASL/SSL Configuration

```properties
# server.properties
listeners=SASL_SSL://0.0.0.0:9093
ssl.keystore.location=/etc/kafka/secrets/kafka.keystore.jks
ssl.keystore.password=***
ssl.key.password=***
ssl.truststore.location=/etc/kafka/secrets/kafka.truststore.jks
ssl.truststore.password=***
ssl.client.auth=required

sasl.enabled.mechanisms=SCRAM-SHA-512
sasl.mechanism.inter.broker.protocol=SCRAM-SHA-512
security.inter.broker.protocol=SASL_SSL

# ACLs
authorizer.class.name=kafka.security.authorizer.AclAuthorizer
super.users=User:kafka-admin
```

### Topic Authorization

```bash
# Producer access
kafka-acls --bootstrap-server localhost:9093 \
  --add --allow-principal User:sayvors-api \
  --producer --topic review-events \
  --producer --topic google-business-events \
  --producer --topic outbox-events

# Consumer access
kafka-acls --bootstrap-server localhost:9093 \
  --add --allow-principal User:sayvors-analytics \
  --consumer --topic review-events \
  --group sayvors-analytics-group
```

## Monitoring & Alerting

### Security Events to Monitor

| Event | Source | Alert Threshold |
|-------|--------|-----------------|
| Failed login | Auth logs | > 10/min per IP |
| Token refresh failure | Auth logs | > 5/min |
| 401/403 errors | API logs | > 5% of requests |
| Rate limit hits | Redis/API | > 100/min |
| Webhook signature failures | Channel logs | > 1% |
| DB connection failures | DB logs | > 5/min |
| Container restarts | K8s events | > 3/hour |
| Secret access anomalies | CloudTrail | Any unauthorized |

### Logging Infrastructure

```
Application → Fluent Bit → Elasticsearch/OpenSearch → Grafana/Kibana
                ↓
            CloudWatch (AWS)
```

### Key Dashboards

1. **Auth Dashboard** - Login success/failure, token refresh, lockouts
2. **API Security** - 4xx/5xx rates, rate limits, IDOR attempts
3. **Infrastructure** - Container health, resource usage, network
4. **Data Access** - DB queries, Redis ops, Kafka lag
5. **Compliance** - Audit trail, data access, deletions

## Vulnerability Management

### Container Base Images

```bash
# Weekly rebuild of base images
# Automated via Dependabot/Renovate

# Dockerfile
FROM python:3.12-slim-bookworm  # Specific tag, not latest
```

### Dependency Scanning

```yaml
# .github/workflows/security.yml
- name: Python dependencies
  run: pip-audit --desc --format=json --output=pip-audit.json

- name: Container
  run: trivy fs --severity HIGH,CRITICAL .

- name: SAST
  run: bandit -r services/api/app/ -f json -o bandit.json
```

### Patch SLA

| Severity | SLA |
|----------|-----|
| Critical (CVSS 9-10) | 72 hours |
| High (CVSS 7-8.9) | 7 days |
| Medium (CVSS 4-6.9) | 30 days |
| Low (CVSS 0-3.9) | Next release |

## Incident Response Infrastructure

### Forensics Readiness

- Immutable logs (S3 Object Lock)
- Database audit logs (pgaudit)
- Container snapshots (EBS snapshots)
- Network flow logs (VPC Flow Logs)
- API Gateway access logs

### Isolation Procedures

```bash
# Compromised container
kubectl label pod <pod> quarantine=true
kubectl annotate pod <pod> security.incident/isolated="true"

# Network isolation
kubectl apply -f - <<EOF
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: quarantine-<pod>
spec:
  podSelector:
    matchLabels:
      security.incident/isolated: "true"
  policyTypes:
  - Ingress
  - Egress
  ingress: []
  egress: []
EOF
```

## Compliance Infrastructure

### SOC 2 Controls Mapping

| Control | Implementation |
|---------|----------------|
| CC6.1 (Logical Access) | RBAC, MFA (planned), least privilege |
| CC6.2 (Credentials) | bcrypt, JWT, rotation, secret manager |
| CC6.7 (Encryption) | TLS 1.2+, AES-256, KMS |
| CC7.2 (Monitoring) | Centralized logging, alerting |
| CC7.4 (Incident Response) | Runbooks, isolation, forensics |
| CC8.1 (Change Management) | GitOps, PR reviews, automated tests |

### Audit Evidence

- Infrastructure as Code (Terraform) → Git history
- Policy as Code (OPA/Kyverno) → Git history
- Scan results → CI artifacts
- Access logs → Centralized logging
- Incident records → Incident management system

## Disaster Recovery

### Backup Strategy

| Component | Frequency | Retention | RPO | RTO |
|-----------|-----------|-----------|-----|-----|
| PostgreSQL | Continuous (WAL) + Daily snapshot | 30 days | < 5 min | < 1 hour |
| Redis | AOF + RDB | 7 days | < 1 sec | < 15 min |
| Kafka | Replication factor 3 | 7 days | 0 | < 5 min |
| Secrets | Automatic (Secrets Manager) | N/A | 0 | < 5 min |
| Config (Git) | Every commit | Forever | 0 | < 10 min |

### Recovery Procedures

1. **Database**: Point-in-time recovery from WAL + snapshot
2. **Redis**: Restore from AOF/RDB, rebuild cache
3. **Kafka**: Rebalance from replicas
4. **Application**: Redeploy from Git (GitOps)
5. **Secrets**: Restore from Secrets Manager

### DR Testing

- Quarterly failover test
- Annual full DR drill
- Documented runbooks
- RTO/RPO validation