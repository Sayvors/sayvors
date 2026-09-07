"""Localith spike — fetch one location's reviews and show the mapping.

Secrets via env (never committed)::

    $env:LOCALITH_API_KEY = "<key from Localith Account > API key>"
    # optional overrides (defaults come from embedsocial.py):
    # $env:LOCALITH_BASE_URL = "https://embedsocial.com/app/api"
    # $env:LOCALITH_REVIEWS_PATH = "reviews"
    python scripts/embedsocial_spike.py [--limit 10] [--raw]
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integrations.channels import embedsocial  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Localith reviews spike")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--raw", action="store_true", help="dump first raw item JSON")
    args = parser.parse_args()

    try:
        items = embedsocial.fetch_reviews(limit=args.limit)
    except Exception as e:  # noqa: BLE001 — spike: show the raw failure
        print(f"FETCH FAILED: {type(e).__name__}: {e}")
        return 1

    print(f"fetched {len(items)} raw item(s)")
    if not items:
        print("empty result — check key/plan/path; if you see an auth error "
              "the API key needs a paid plan")
        return 2

    if args.raw:
        print("--- first raw item ---")
        print(json.dumps(items[0], indent=2, ensure_ascii=False)[:3000])

    print("--- mapped ---")
    for item in items[: args.limit]:
        r = embedsocial.to_internal_review(item if isinstance(item, dict) else {})
        text = (r.reviewer or "?") + f" [{r.rating}/5]"
        body = (r.text or "(no text)")[:100].replace("\n", " ")
        print(f"- {text}: {body}  <{r.platform} | {r.external_id[:24]}>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
