"""CSV upload + query Pydantic schemas."""
from pydantic import BaseModel, Field


class CSVUploadResponse(BaseModel):
    id: str
    filename: str
    column_names: list[str] | None = None
    row_count: int
    purpose: str | None = None


class CSVRowOut(BaseModel):
    id: str
    row_index: int
    data: dict


class CSVSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    upload_id: str | None = Field(default=None, max_length=36)
    purpose: str | None = Field(default=None, max_length=32)
    filters: dict | None = Field(default=None)
    limit: int = Field(default=5, ge=1, le=50)


class CSVSearchResult(BaseModel):
    rows: list[CSVRowOut]
    total_matches: int


class ToolSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    category: str | None = Field(default=None, max_length=100)
    filters: dict | None = Field(default=None)
    limit: int = Field(default=5, ge=1, le=20)


class ToolSearchResult(BaseModel):
    results: list[dict]
    count: int
    tool_name: str
