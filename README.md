# Sayvors

Monorepo for the Sayvors platform.

## Structure

```
apps/                        User-facing applications
  web/                       Next.js Customer App
  admin/                     Internal Dashboard
  docs/                      Documentation Site
services/                    Business Microservices
integrations/                External APIs & Third-party Platforms
  channels/
  payments/
  ai/
  storage/
  email/
  sms/
  webhooks/
deployments/                 Environment-specific deployment
configs/                     Global configuration templates
scripts/                     Automation scripts
tools/                       Internal developer tools
tests/                       Cross-service integration tests
docs/                        Architecture docs & ADRs
.github/                     GitHub Actions
```
