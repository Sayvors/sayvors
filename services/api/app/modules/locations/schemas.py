from datetime import date

from pydantic import BaseModel, Field


class LocationSummary(BaseModel):
    listing_id: str
    name: str
    address: str | None = None
    phone: str | None = None
    website: str | None = None
    maps_url: str | None = None
    status: str
    rating: float | None = None
    reviews: int = 0
    source: str  # "google"


class CategoriesIn(BaseModel):
    primary: str | None = None
    additional: list[str] | None = None


class HoursIn(BaseModel):
    regular: dict[str, dict] | None = None
    special: list[dict] | None = None
    more: list[dict] | None = None


class LocationUpdate(BaseModel):
    # Google Business Information API identity fields. Address is read-only:
    # Google expects a structured postal address, not free text.
    name: str | None = Field(None, max_length=255)
    phone: str | None = Field(None, max_length=40)
    website: str | None = Field(None, max_length=255)
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


class LocationCreateIn(BaseModel):
    """The minimum Google needs to create a storefront location."""

    name: str = Field(..., min_length=1, max_length=255)
    category: str = Field(..., min_length=1, max_length=255)
    street: str = Field(..., min_length=1, max_length=255)
    city: str = Field(..., min_length=1, max_length=120)
    postal_code: str | None = Field(None, max_length=20)
    country: str = Field(..., min_length=2, max_length=2)
    phone: str = Field(..., min_length=1, max_length=40)
    website: str | None = Field(None, max_length=255)
    request_id: str | None = Field(None, max_length=50)


class GoogleLocationMatchOut(BaseModel):
    name: str
    location_name: str | None = None
    address: str | None = None
    place_id: str | None = None
    request_admin_rights_url: str | None = None


class LocationCreateOut(BaseModel):
    listing_id: str
    channel_id: str
    name: str
    address: str | None = None
    status: str = "active"
    created: bool = True


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
