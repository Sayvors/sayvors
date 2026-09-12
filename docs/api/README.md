# Sayvors API Documentation

This directory contains the API documentation for the Sayvors platform.

## Contents

- [Overview](overview.md) — API overview, base URL, authentication
- [Endpoints](endpoints.md) — Complete endpoint reference
- [Authentication](authentication.md) — JWT, cookies, CSRF
- [Rate Limiting](rate-limiting.md) — Rate limit policies
- [Error Handling](error-handling.md) — Error formats and codes
- [Webhooks](webhooks.md) — Incoming webhook handling
- [SDK & Examples](examples.md) — Code examples

## Quick Start

```bash
# Base URL (development)
http://localhost:8000

# Base URL (production)
https://api.sayvors.com

# Health check
GET /health
```

## API Versioning

All endpoints are prefixed with `/api/v1`. Breaking changes will result in a new version (e.g., `/api/v2`).

## Content Types

- Request: `application/json`
- Response: `application/json`
- File uploads: `multipart/form-data`

## OpenAPI Spec

The OpenAPI 3.0 specification is available at:
- Development: `http://localhost:8000/openapi.json`
- Interactive docs: `http://localhost:8000/docs` (Swagger UI)
- ReDoc: `http://localhost:8000/redoc`