"""What Google shows today, per section.

The consumer view of a listing is what a customer sees right now, which can
lag the merchant's own submission while Google reviews it. These tests pin
the translation from Google's shapes to Sayvors'.
"""
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.modules.channels.google_business import (
    google_periods_to_hours,
    google_special_hours_to_entries,
    parse_attribute_values,
    parse_consumer_values,
)


def test_consumer_values_reads_the_live_listing():
    extended = {
        "locationSeenByConsumers": {
            "title": "Sayvors Company Branch-Al Malqa",
            "phoneNumbers": {"primaryPhone": "053 564 3335"},
            "websiteUri": "https://sayvors.com/",
            "profile": {"description": "A platform for business"},
            "storefrontAddress": {"locality": "Al Malqa", "regionCode": "SA"},
            "categories": {
                "primaryCategory": {"displayName": "Software company"},
                "additionalCategories": [{"displayName": "Consulting"}],
            },
            "regularHours": {
                "periods": [
                    {
                        "openDay": "SUNDAY",
                        "openTime": {},
                        "closeDay": "SUNDAY",
                        "closeTime": {"hours": 24},
                    }
                ]
            },
            "specialHours": {
                "specialHourPeriods": [
                    {
                        "startDate": {"year": 2026, "month": 11, "day": 12},
                        "endDate": {"year": 2026, "month": 11, "day": 12},
                        "openTime": {"hours": 9},
                        "closeTime": {"hours": 21},
                    }
                ]
            },
        }
    }
    values = parse_consumer_values(extended)
    assert values["name"] == "Sayvors Company Branch-Al Malqa"
    assert values["phone"] == "053 564 3335"
    assert values["website"] == "https://sayvors.com/"
    assert values["description"] == "A platform for business"
    assert values["categories"] == {
        "primary": "Software company",
        "additional": ["Consulting"],
    }
    assert values["hours.regular"]["Sunday"]["all_day"] is True
    assert values["hours.regular"]["Monday"]["closed"] is True
    assert values["hours.special"][0]["date"] == "2026-11-12"
    assert values["hours.special"][0]["hours"] == "09:00 - 21:00"


def test_consumer_values_of_an_empty_listing():
    assert parse_consumer_values({}) == {}
    assert parse_consumer_values({"locationSeenByConsumers": {}}) == {}


def test_periods_to_hours_reads_an_overnight_range():
    hours = google_periods_to_hours(
        [
            {
                "openDay": "FRIDAY",
                "openTime": {"hours": 20, "minutes": 0},
                "closeDay": "SATURDAY",
                "closeTime": {"hours": 2, "minutes": 0},
            }
        ]
    )
    assert hours["Friday"]["open"] == "20:00"
    assert hours["Friday"]["close"] == "02:00"
    assert hours["Friday"]["closed"] is False
    assert hours["Saturday"]["open"] == "02:00"
    assert hours["Saturday"]["close"] == "20:00"


def test_special_hours_marks_a_closed_day():
    entries = google_special_hours_to_entries(
        [
            {
                "startDate": {"year": 2026, "month": 12, "day": 25},
                "endDate": {"year": 2026, "month": 12, "day": 25},
                "closed": True,
            }
        ]
    )
    assert entries == [{"date": "2026-12-25", "hours": "Closed", "reason": ""}]


def test_attribute_values_use_the_consumer_view():
    extended = {
        "extendedAttributes": [
            {
                "attributeProvidedByMerchant": {"name": "attributes/wifi"},
                "attributeSeenByConsumers": {
                    "name": "attributes/wifi",
                    "valueType": "BOOLEAN",
                    "booleanValue": True,
                },
                "extendedFieldData": {},
            },
            {
                "attributeSeenByConsumers": {
                    "name": "attributes/url_facebook",
                    "valueType": "URL",
                    "uriValues": [{"uri": "https://facebook.com/sayvors"}],
                },
            },
        ]
    }
    values = parse_attribute_values(extended)
    assert values["wifi"] == "yes"
    assert values["url_facebook"] == "https://facebook.com/sayvors"


def test_attribute_values_of_an_empty_response():
    assert parse_attribute_values({}) == {}
    assert parse_attribute_values({"extendedAttributes": None}) == {}
