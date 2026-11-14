"""Google location snapshot → Locations page fields (hours/categories/…)."""
from app.modules.channels.google_reviews import (
    location_attributes,
    location_categories,
    location_hours,
    location_service_area,
    location_service_types,
)


def _loc() -> dict:
    return {
        "regularHours": {"periods": [
            {"openDay": "MONDAY", "openTime": {}, "closeDay": "MONDAY",
             "closeTime": {"hours": 24}},
            {"openDay": "FRIDAY", "openTime": {"hours": 9, "minutes": 0},
             "closeDay": "FRIDAY", "closeTime": {"hours": 17, "minutes": 30}},
        ]},
        "specialHours": {"specialHourPeriods": [
            {"startDate": {"year": 2026, "month": 12, "day": 25}, "closed": True},
            {"startDate": {"year": 2026, "month": 12, "day": 31},
             "openTime": {"hours": 9}, "closeTime": {"hours": 13}},
        ]},
        "moreHours": [
            {"hoursTypeId": "DELIVERY", "periods": [
                {"openDay": "MONDAY", "openTime": {"hours": 10},
                 "closeDay": "MONDAY", "closeTime": {"hours": 22}},
            ]},
        ],
        "categories": {
            "primaryCategory": {
                "displayName": "Software company",
                "serviceTypes": [{"displayName": "Software development"}],
            },
            "additionalCategories": [
                {"displayName": "Consultant",
                 "serviceTypes": [{"displayName": "IT consulting"}]},
            ],
        },
        "serviceArea": {"places": [{"placeName": "Riyadh"}]},
    }


def test_regular_hours_map_including_all_day_and_closed_days():
    hours = location_hours(_loc())["regular"]
    assert hours["Monday"] == {
        "open": "00:00", "close": "00:00", "closed": False, "all_day": True,
    }
    assert hours["Friday"] == {"open": "09:00", "close": "17:30", "closed": False}
    # No period = Google says closed.
    assert hours["Tuesday"]["closed"] is True


def test_special_and_more_hours_map():
    hours = location_hours(_loc())
    assert hours["special"] == [
        {"date": "2026-12-25", "hours": "closed", "reason": ""},
        {"date": "2026-12-31", "hours": "09:00 - 13:00", "reason": ""},
    ]
    assert hours["more"] == [
        {"type": "Delivery", "open": "10:00", "close": "22:00"},
    ]


def test_categories_and_services_import():
    loc = _loc()
    assert location_categories(loc) == {
        "primary": "Software company", "additional": ["Consultant"],
    }
    assert location_service_types(loc) == ["Software development", "IT consulting"]


def test_attributes_keep_booleans_and_skip_url_values():
    attrs = location_attributes([
        {"name": "attributes/has_wifi", "values": [{"boolValue": True}]},
        {"name": "attributes/allows_dogs", "values": [{"boolValue": False}]},
        {"name": "attributes/url_text_messaging",
         "values": [{"uriValues": [{"uri": "sms:+966"}]}]},
    ])
    assert attrs == {"Free wifi": "yes", "Pet friendly": "no"}


def test_service_area_maps_place_names():
    assert location_service_area(_loc()) == ["Riyadh"]


def test_service_area_tolerates_bare_string_places():
    """Some Google accounts return place-name strings instead of objects —
    a str element must not crash the parser (staging 500 on connect)."""
    loc = _loc()
    loc["serviceArea"] = {"places": ["Riyadh", "Jeddah"]}
    assert location_service_area(loc) == ["Riyadh", "Jeddah"]


def test_service_area_mixed_shapes_dedupes_and_skips_blank():
    loc = _loc()
    loc["serviceArea"] = {
        "places": [{"placeName": "Riyadh"}, "Jeddah", "", None],
        "regionCode": "SA",
    }
    assert location_service_area(loc) == ["Riyadh", "Jeddah", "SA"]
