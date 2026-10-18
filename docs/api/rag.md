# RAG Databanks

The RAG API lets an authenticated user maintain separate knowledge databanks,
ingest files or website content, search indexed chunks, connect a live database
as a read-only source, and ask an AI agent questions using the available
databank tools.

All routes use the `/api/v1/rag` prefix and require an authenticated user.
Databanks, documents, and database sources are scoped to their owner. The
complete route list is in the [API endpoint reference](endpoints.md#rag-apiv1rag).

## Create a databank

```http
POST /api/v1/rag/databanks
Content-Type: application/json
Authorization: Bearer <access-token>
X-CSRF-Token: <csrf-token>

{
  "name": "Business handbook",
  "description": "Policies and service information",
  "accent_color": "#265f4a"
}
```

Save the returned `id`; subsequent requests use it as `{databank_id}`.

## Add documents and website content

Upload a file using multipart form data. The API starts processing after the
upload; the document status and chunk count are returned with its metadata.

```powershell
curl.exe -X POST "http://localhost:8000/api/v1/rag/databanks/<databank_id>/documents" `
  -H "Authorization: Bearer <access-token>" `
  -H "X-CSRF-Token: <csrf-token>" `
  -F "file=@handbook.pdf"
```

To scrape a website, request a single page or a bounded crawl. `crawl_mode` is
`single` or `full`; `max_pages` is limited to 1–500.

```http
POST /api/v1/rag/databanks/<databank_id>/scrape
Content-Type: application/json
Authorization: Bearer <access-token>
X-CSRF-Token: <csrf-token>

{
  "url": "https://example.com/help/",
  "crawl_mode": "full",
  "max_pages": 50
}
```

The scrape route creates a scrape job. Use `GET /api/v1/rag/jobs` to inspect
ingestion jobs. If documents remain pending, `POST
/api/v1/rag/databanks/{databank_id}/process` queues pending work; the
document-specific `/documents/{doc_id}/process` route queues one document.
Both processing routes return `202 Accepted` with job metadata. Job states,
progress, stage, and errors are included in job responses.

List documents with `GET /api/v1/rag/databanks/{databank_id}/documents`.
Preview parsed content with `GET
/api/v1/rag/databanks/{databank_id}/documents/{doc_id}/preview`; `page` and
`page_size` paginate the preview. Delete a document with `DELETE
/api/v1/rag/databanks/{databank_id}/documents/{doc_id}`.

## Search and ask

Search returns matching chunks and scores. `top_k` defaults to 5 and may be
between 1 and 50.

```http
POST /api/v1/rag/databanks/<databank_id>/search
Content-Type: application/json
Authorization: Bearer <access-token>
X-CSRF-Token: <csrf-token>

{
  "query": "What is our return policy?",
  "top_k": 5
}
```

The response includes `degraded` and an optional `notice`. If no embedding
backend is available, the service reports that vector search is unavailable
and returns keyword results instead.

For a composed answer, use `/ask`. This invokes the tenant's configured model
with access to databank retrieval tools; the response includes citations and a
bounded execution trace.

```http
POST /api/v1/rag/databanks/<databank_id>/ask
Content-Type: application/json
Authorization: Bearer <access-token>
X-CSRF-Token: <csrf-token>

{
  "question": "What is our return policy?",
  "top_k": 5,
  "max_steps": 6
}
```

`top_k` is limited to 1–20 and `max_steps` to 1–10. The tenant must have an
enabled AI model configured for agent answers.

## Connect a live database

The source workflow supports PostgreSQL and MySQL:

1. Call `POST /databanks/{databank_id}/sources/test` with connection details to
   check a connection without saving it.
2. Call `POST /databanks/{databank_id}/sources` with the same details and a
   source name to test and save it.
3. Use `GET /databanks/{databank_id}/sources/{source_id}/schema` to list tables,
   then `GET /databanks/{databank_id}/sources/{source_id}/tables/{table}` to
   preview rows (`limit` defaults to 20, maximum 100).
4. `POST /databanks/{databank_id}/sources/{source_id}/query` runs a live,
   read-only `SELECT` or `WITH` query. Its `limit` defaults to 200 and is
   capped at 1,000.
5. To index query results for later retrieval, use
   `POST /databanks/{databank_id}/sources/{source_id}/ingest` with a SQL query,
   optional `name`, and a result limit (default 500, maximum 1,000).

Passwords for saved sources are stored encrypted. Queries are intended for
read-only access; use a dedicated database account with the minimum required
privileges. By default, RAG database connections must resolve to globally
routable hosts. `RAG_DB_ALLOW_PRIVATE_HOSTS` relaxes this SSRF safeguard and
production startup rejects it when enabled. See
[API configuration](configuration.md#test-and-security-sensitive-switches).

## Reindex, retry, and delete

- `POST /databanks/{databank_id}/reindex` queues re-embedding all documents,
  for example after changing the embedding backend.
- `POST /databanks/{databank_id}/retry` retries pending, processing, or failed
  documents. Optionally provide `{"document_ids": ["..."]}` to select
  documents.
- `DELETE /databanks/{databank_id}/sources/{source_id}` removes a live database
  source.
- `DELETE /databanks/{databank_id}` deletes the databank and its contents.

Queued operations run through the RAG worker. Ensure the API background-worker
configuration or dedicated worker deployment is active; see
[API configuration](configuration.md#core-services-and-runtime).
