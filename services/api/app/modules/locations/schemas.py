from datetime import date

from pydantic import BaseModel, Field


class LocationSummary(BaseModel):
    listing_id: str
    name: str
    address: str | None = None
    status: str
    source: str  # "localith" | "channel"


class CategoriesIn(BaseModel):
    primary: str | None = None
    additional: list[str] | None = None


class HoursIn(BaseModel):
    regular: dict[str, dict] | None = None
    special: list[dict] | None = None
    more: list[dict] | None = None


class LocationUpdate(BaseModel):
    description: str | None = Field(None, max_length=750)
    categories: CategoriesIn | None = None
    hours: HoursIn | None = None
    service_area: list[str] | None = None
    attributes: dict[str, str] | None = None
    opening_date: date | None = Field(None, description="Business opening date (YYYY-MM-DD)")


class LocationGroupIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    listing_ids: list[str] = []


class LocationGroupOut(BaseModel):
    id: str
    name: str
    listing_ids: list[str] = []
    position: int = 0


class LocationGroupUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    listing_ids: list[str] | None = None


class LocationProfileOut(BaseModel):
    listing_id: str
    name: str
    address: str | None = None
    phone: str | None = None
    website: str | None = None
    maps_url: str | None = None
    status: str
    is_verified: bool | None = None
    description: str | None = None
    categories: dict = {}
    hours: dict = {}
    service_area: list[str] = []
    attributes: dict[str, str] = {}
    opening_date: str | None = None
    google_synced: list[str] = []
    updated_at: str | None = None
