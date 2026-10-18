# Architecture Documentation

This directory contains architecture documentation for the Sayvors platform.

## Contents

- [Overview](overview.md) — System architecture, components, data flow
- [API Service](api-service.md) — FastAPI service internals
- [Google review, ticket, and lead flow](google-review-ticket-lead-flow.md) — Review follow-up lifecycle
- [Database](../database/README.md) — Database setup and storage backends
- [Meta integration architecture](../integrations/meta/architecture.md) — Meta connections, OAuth, assets, and webhooks
- [API environment configuration](../api/configuration.md) — Runtime settings, secrets, and deployment configuration
- [Worker and job operations](../operations/workers-and-jobs.md) — Dedicated workers, job lanes, and operational checks

Detailed architecture pages are linked here only when they exist. API operation
details are in the [endpoint reference](../api/endpoints.md); deployment
checklists and ongoing implementation notes are in [tracking](../tracking/README.md).