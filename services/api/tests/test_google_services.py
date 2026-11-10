"""Google service-list push: what reaches Google and what does not.

No network: the Google client is monkeypatched. The tests pin the rules the
rebuild follows — only the services the merchant declared are published, a
service they undeclared leaves the list, and the v1 payload shape is the one
the API accepts.
"""
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.modules.channels import google_services
from app.modules.channels.google_services import (
    build_service_items,
    location_category_info,
)

CATEGORY = "categories/gcid:software_company"

# The category's service types, as the location reports them.
SERVICE_TYPES = {
    "data center management": "job_type_id:data_center_management",
    "software development": "job_type_id:software_development",
}


class _Row:
    """A stand-in for a BusinessService row."""

    def __init__(
        self,
        name,
        source="custom",
        description=None,
        is_offered=True,
        declared=True,
    ):
        self.name = name
        self.source = source
        self.description = description
        self.is_offered = is_offered
        self.declared = declared


def _free_form(name, description=None):
    item = {
        "freeFormServiceItem": {
            "category": CATEGORY,
            "label": {"displayName": name, "languageCode": "en"},
        }
    }
    if description:
        item["freeFormServiceItem"]["label"]["description"] = description
    return item


def _structured(service_id):
    return {"structuredServiceItem": {"serviceTypeId": service_id}}


def test_location_category_info_reads_the_primary_category():
    location = {
        "categories": {
            "primaryCategory": {
                "name": CATEGORY,
                "serviceTypes": [
                    {
                        "serviceTypeId": "job_type_id:data_center_management",
                        "displayName": "Data center management",
                    },
                ],
            }
        }
    }
    category_id, service_ids = location_category_info(location)
    assert category_id == CATEGORY
    assert service_ids["data center management"] == "job_type_id:data_center_management"


def test_build_publishes_a_declared_custom_service():
    items, skipped = build_service_items(
        google_items=[],
        local_rows=[_Row("Consulting", description="We advise")],
        category_id=CATEGORY,
        service_type_ids=SERVICE_TYPES,
    )
    assert skipped == []
    assert items == [
        {
            "freeFormServiceItem": {
                "category": CATEGORY,
                "label": {
                    "displayName": "Consulting",
                    "languageCode": "en",
                    "description": "We advise",
                },
            }
        }
    ]
    # The v1 API rejects an offered flag on a service item.
    assert "isOffered" not in str(items)


def test_build_publishes_a_declared_catalogue_service_as_a_structured_item():
    items, _ = build_service_items(
        google_items=[],
        local_rows=[
            _Row("Data center management", source="google", declared=True),
        ],
        category_id=CATEGORY,
        service_type_ids=SERVICE_TYPES,
    )
    assert items == [
        {"structuredServiceItem": {"serviceTypeId": "job_type_id:data_center_management"}}
    ]


def test_build_does_not_publish_an_undeclared_catalogue_service():
    """The category catalogue is a suggestion, not the merchant's list."""
    items, _ = build_service_items(
        google_items=[],
        local_rows=[
            _Row("Data center management", source="google", declared=False),
        ],
        category_id=CATEGORY,
        service_type_ids=SERVICE_TYPES,
    )
    assert items == []


def test_build_removes_a_service_the_merchant_undeclared():
    items, _ = build_service_items(
        google_items=[_structured("job_type_id:data_center_management")],
        local_rows=[
            _Row("Data center management", source="google", declared=False),
        ],
        category_id=CATEGORY,
        service_type_ids=SERVICE_TYPES,
    )
    assert items == []


def test_build_keeps_a_declared_service_google_already_holds():
    items, _ = build_service_items(
        google_items=[_structured("job_type_id:data_center_management")],
        local_rows=[
            _Row("Data center management", source="google", declared=True),
        ],
        category_id=CATEGORY,
        service_type_ids=SERVICE_TYPES,
    )
    assert items == [
        {"structuredServiceItem": {"serviceTypeId": "job_type_id:data_center_management"}}
    ]


def test_build_drops_a_custom_service_the_merchant_deleted():
    items, _ = build_service_items(
        google_items=[_free_form("Old service")],
        local_rows=[],
        category_id=CATEGORY,
        service_type_ids=SERVICE_TYPES,
    )
    assert items == []


def test_build_refreshes_a_custom_service_that_is_still_local():
    items, _ = build_service_items(
        google_items=[_free_form("Consulting")],
        local_rows=[_Row("Consulting", description="Now with details")],
        category_id=CATEGORY,
        service_type_ids=SERVICE_TYPES,
    )
    assert len(items) == 1
    label = items[0]["freeFormServiceItem"]["label"]
    assert label["displayName"] == "Consulting"
    assert label["description"] == "Now with details"


def test_build_keeps_a_structured_service_it_cannot_map():
    """A service set directly in Google's own UI is not ours to remove."""
    google_item = _structured("job_type_id:hair_styling")
    items, _ = build_service_items(
        google_items=[google_item],
        local_rows=[],
        category_id=CATEGORY,
        service_type_ids=SERVICE_TYPES,
    )
    assert items == [google_item]


def test_build_skips_a_custom_service_without_a_category():
    items, skipped = build_service_items(
        google_items=[],
        local_rows=[_Row("Consulting")],
        category_id="",
        service_type_ids=SERVICE_TYPES,
    )
    assert items == []
    assert skipped == ["Consulting"]


def test_location_id_of_prefers_the_google_location_id():
    class _Ch:
        platform_user_id = "acc"
        listing_key = "key"
        id = "ch-1"
        metadata_json = '{"location_id": "loc-9"}'

    assert google_services._location_id_of(_Ch()) == "loc-9"


@pytest.mark.asyncio
async def test_push_services_reports_a_missing_credential(db, user_id):
    from app.modules.channels.models import Channel

    channel = Channel(
        id="ch-no-token",
        user_id=user_id,
        platform="google_reviews",
        platform_user_id="loc-1",
        status="active",
        listing_key="loc-1",
    )
    db.add(channel)
    await db.commit()

    result = await google_services.push_services(db, channel)
    assert result["pushed"] is False
    assert "credential" in (result["error"] or "")
