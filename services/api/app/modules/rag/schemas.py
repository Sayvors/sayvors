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
