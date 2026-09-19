from datetime import datetime

from pydantic import BaseModel, Field


class DatabankCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    accent_color: str | None = None


class DatabankResponse(BaseModel):
    id: str
    name: str
    description: str | None = None
    accent_color: str | None = None
    doc_count: int = 0
    total_size: int = 0
    created_at: datetime


class DatabankListResponse(BaseModel):
    databanks: list[DatabankResponse]
    total: int


class DocumentResponse(BaseModel):
    id: str
    filename: str
    source_type: str
    source_url: str | None = None
    file_type: str
    size_bytes: int = 0
    status: str
    chunk_count: int = 0
    created_at: datetime


class DocumentListResponse(BaseModel):
    documents: list[DocumentResponse]
    total: int


class ScrapeRequest(BaseModel):
    url: str = Field(..., min_length=1)
    crawl_mode: str = Field(default="single", pattern="^(single|full)$")
    max_pages: int = Field(default=50, ge=1, le=500)


class ScrapeJobResponse(BaseModel):
    id: str
    url: str
    crawl_mode: str
    status: str
    pages_found: int = 0
    error: str | None = None
    created_at: datetime


class IngestJobResponse(BaseModel):
    id: str
    job_type: str
    status: str
    progress: int = 0
    stage: str | None = None
    error: str | None = None
    created_at: datetime


class IngestJobListResponse(BaseModel):
    jobs: list[IngestJobResponse]
    total: int


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    top_k: int = Field(default=5, ge=1, le=50)


class SearchChunkResponse(BaseModel):
    content: str
    score: float
    document_id: str
    metadata_: dict | None = None


class SearchResponse(BaseModel):
    chunks: list[SearchChunkResponse]
    query: str
    degraded: bool = False
    notice: str | None = None


class DatabaseConnection(BaseModel):
    db_type: str = Field(default="postgres", pattern="^(postgres|mysql)$")
    host: str = Field(default="localhost", min_length=1, max_length=255)
    port: int | None = Field(None, ge=1, le=65535)
    database: str = Field(..., min_length=1, max_length=255)
    username: str = Field(..., min_length=1, max_length=255)
    password: str | None = Field(None, max_length=1024)


class DatabaseSourceCreate(DatabaseConnection):
    name: str = Field(..., min_length=1, max_length=255)


class DatabaseSourceResponse(BaseModel):
    id: str
    name: str
    db_type: str
    host: str
    port: int
    database: str
    username: str
    created_at: datetime


class DatabaseSourceListResponse(BaseModel):
    sources: list[DatabaseSourceResponse]
    total: int


class DatabaseTestResponse(BaseModel):
    ok: bool
    version: str | None = None
    error: str | None = None


class TableInfo(BaseModel):
    name: str
    columns: int


class SchemaResponse(BaseModel):
    source_id: str
    tables: list[TableInfo]


class TablePreviewResponse(BaseModel):
    table: str
    columns: list[str]
    rows: list[list]
    truncated: bool


class QueryRequest(BaseModel):
    sql: str = Field(..., min_length=1, max_length=20000)
    limit: int = Field(default=200, ge=1, le=1000)


class QueryResponse(BaseModel):
    columns: list[str]
    rows: list[list]
    row_count: int
    truncated: bool


class IngestQueryRequest(BaseModel):
    sql: str = Field(..., min_length=1, max_length=20000)
    name: str | None = Field(None, max_length=255)
    limit: int = Field(default=500, ge=1, le=1000)


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=4000)
    top_k: int = Field(default=5, ge=1, le=20)
    max_steps: int = Field(default=6, ge=1, le=10)


class TraceStep(BaseModel):
    step: int
    thought: str = ""
    tool: str | None = None
    args: dict = {}
    ms: int = 0
    observation: str = ""


class Citation(BaseModel):
    source: str
    kind: str
    detail: str = ""


class AskResponse(BaseModel):
    answer: str
    citations: list[Citation]
    trace: list[TraceStep]
    steps_used: int
    model: str
