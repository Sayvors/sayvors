# Sayvors Admin App

Internal platform-operations dashboard built with Next.js. It uses the API's
separate platform-admin authentication (not a customer account) and an httpOnly
session cookie.

## Routes

| Route | Purpose |
|-------|---------|
| `/login` | Platform-admin sign-in |
| `/overview` | Platform totals, windowed and live activity, service health |
| `/tenants` | Tenant list and tenant details |
| `/usage` | Platform-wide usage and metering |
| `/llms` | Provider configuration, model availability, and provider tests |
| `/voice` | Voice engines and voice catalog tools |
| `/feedback` | Submitted customer feedback |
| `/logs` | Operational logs |

## Local development

The app defaults to an API at `http://localhost:8000`. Set
`NEXT_PUBLIC_API_URL` at build time when using another API origin. Start the
development server with:

```bash
npm run dev
```

The API must be configured with `ADMIN_PASSWORD_HASH` to enable admin login;
see [API configuration](../../docs/api/configuration.md). The app sends
credentials to the API and does not store the admin token in browser storage.

## Quality checks

```bash
npm run lint
npm run build
```
