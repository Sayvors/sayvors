from datetime import date

from pydantic import BaseModel, Field, model_validator


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


class LocationSearchIn(BaseModel):
    """Search Google for matching listings.

    The full create payload is not needed: Google only requires ``title`` for
    a location search. The wizard uses this for the name suggestions and again
    with the complete address before creating.
    """

    name: str = Field(..., min_length=1, max_length=255)
    category: str | None = Field(None, max_length=255)
    street: str | None = Field(None, max_length=255)
    city: str | None = Field(None, max_length=120)
    state: str | None = Field(None, max_length=120)
    postal_code: str | None = Field(None, max_length=20)
    country: str | None = Field(None, min_length=2, max_length=2)
    phone: str | None = Field(None, max_length=40)
    has_storefront: bool = True


class LocationCreateIn(BaseModel):
    """Everything the page wizard collects before creating a location."""

    name: str = Field(..., min_length=1, max_length=255)
    category: str = Field(..., min_length=1, max_length=255)
    has_storefront: bool = True
    street: str | None = Field(None, max_length=255)
    city: str | None = Field(None, max_length=120)
    state: str | None = Field(None, max_length=120)
    postal_code: str | None = Field(None, max_length=20)
    country: str = Field(..., min_length=2, max_length=2)
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)
    phone: str = Field(..., min_length=1, max_length=40)
    website: str | None = Field(None, max_length=255)
    description: str | None = Field(None, max_length=750)
    language_code: str = Field("en", min_length=2, max_length=10)
    # Free-text areas; resolved to Google place IDs server-side.
    service_area: list[str] | None = None
    request_id: str | None = Field(None, max_length=50)

    @model_validator(mode="after")
    def _validate_required_fields(self):
        if self.has_storefront and not (self.street and self.city):
            raise ValueError("A storefront location needs a street and city.")
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must be provided together.")
        return self


class GoogleLocationMatchOut(BaseModel):
    name: str
    location_name: str | None = None
    address: str | None = None
    place_id: str | None = None
    request_admin_rights_url: str | None = None


class LocationCategoryOut(BaseModel):
    name: str
    display_name: str


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
    country: str | None = None
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
    # google_synced is cumulative (what Google currently has); google_pushed
    # is just this save, for the "Synced to Google" banner.
    google_synced: list[str] = []
    google_pushed: list[str] = []
    google_skipped: dict[str, str] = {}
    updated_at: str | None = None
