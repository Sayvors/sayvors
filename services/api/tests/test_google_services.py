"""Google service-list push: what reaches Google and what does not.

No network: the Google client is monkeypatched. The tests pin the rules the
rebuild follows — Google's own entries survive, a custom service the merchant
deleted leaves Google's list, and the v1 payload shape is the one the API
accepts.
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


class _Row:
    """A stand-in for a BusinessService row."""

    def __init__(self, name, source="custom", description=None, is_offered=True):
        self.name = name
        self.source = source
        self.description = description
        self.is_offered = is_offered


def _free_form(name, description=None):
    item = {
        "freeFormServiceItem": {
            "category": "categories/gcid:software_company",
            "label": {"displayName": name, "languageCode": "en"},
        }
    }
    if description:
        item["freeFormServiceItem"]["label"]["description"] = description
    return item


def test_location_category_info_reads_the_primary_category():
    location = {
        "categories": {
            "primaryCategory": {
                "name": "categories/gcid:software_company",
                "serviceTypes": [
                    {"serviceTypeId": "job_type_id:app_dev", "displayName": "App development"},
                ],
            }
        }
    }
    category_id, service_ids = location_category_info(location)
    assert category_id == "categories/gcid:software_company"
    assert service_ids["app development"] == "job_type_id:app_dev"


def test_build_publishes_custom_services_in_the_v1_shape():
    items, skipped = build_service_items(
        google_items=[],
        local_rows=[_Row("Consulting", description="We advise")],
        category_id="categories/gcid:software_company",
    )
    assert skipped == []
    assert items == [
        {
            "freeFormServiceItem": {
                "category": "categories/gcid:software_company",
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


def test_build_keeps_google_structured_services_untouched():
    google_item = {
        "structuredServiceItem": {"serviceTypeId": "job_type_id:app_dev"}
    }
    items, _ = build_service_items(
        google_items=[google_item],
        local_rows=[_Row("App development", source="google")],
        category_id="categories/gcid:software_company",
    )
    assert items == [google_item]


def test_build_drops_a_custom_service_the_merchant_deleted():
    items, _ = build_service_items(
        google_items=[_free_form("Old service")],
        local_rows=[],
        category_id="categories/gcid:software_company",
    )
    assert items == []


def test_build_refreshes_a_custom_service_that_is_still_local():
    items, _ = build_service_items(
        google_items=[_free_form("Consulting")],
        local_rows=[_Row("Consulting", description="Now with details")],
        category_id="categories/gcid:software_company",
    )
    assert len(items) == 1
    label = items[0]["freeFormServiceItem"]["label"]
    assert label["displayName"] == "Consulting"
    assert label["description"] == "Now with details"


def test_build_skips_a_custom_service_without_a_category():
    items, skipped = build_service_items(
        google_items=[],
        local_rows=[_Row("Consulting")],
        category_id="",
    )
    assert items == []
    assert skipped == ["Consulting"]


def test_build_does_not_publish_google_declared_services():
    """Google's category catalogue is not the merchant's service list."""
    items, _ = build_service_items(
        google_items=[],
        local_rows=[_Row("App development", source="google")],
        category_id="categories/gcid:software_company",
    )
    assert items == []


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
