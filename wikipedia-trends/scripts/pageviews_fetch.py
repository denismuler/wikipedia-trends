"""Fetch Wikipedia pageviews for one article from the Wikimedia REST API.

Thin wrapper around :mod:`pageviews_api` (monthly series, ``agent=user`` by default).

API docs: https://doc.wikimedia.org/generated-data-platform/aqs/analytics-api/reference/page-views.html
Data only exists from 2015-07 onward for modern pageviews. We always request ``agent=user`` to
exclude bots/spiders, which is the closest proxy to genuine human interest.
"""
from __future__ import annotations

import sys

from pageviews_api import DATA_START, fetch_pageviews

__all__ = ["DATA_START", "fetch_pageviews"]


if __name__ == "__main__":
    import argparse
    import json
    from datetime import date

    from common import months_ago, yyyymmdd

    parser = argparse.ArgumentParser(description="Fetch monthly Wikipedia pageviews for one article")
    parser.add_argument("--lang", required=True, help="Wikipedia language code, e.g. pl, cs, uk, en")
    parser.add_argument("--article", required=True, help="exact article title, spaces or underscores")
    parser.add_argument("--months", type=int, default=24, help="how many months back from today")
    parser.add_argument("--start", default=None, help="override: YYYYMMDD")
    parser.add_argument("--end", default=None, help="override: YYYYMMDD, default today")
    parser.add_argument("--granularity", default="monthly", choices=["monthly", "daily"])
    parser.add_argument("--access", default="all-access")
    parser.add_argument("--agent", default="user")
    parser.add_argument("--refresh", action="store_true", help="bypass cache")
    args = parser.parse_args()

    end = args.end or yyyymmdd(date.today())
    start = args.start or yyyymmdd(months_ago(args.months))

    if args.granularity == "monthly":
        result = fetch_pageviews(
            args.lang, args.article, start, end,
            access=args.access, agent=args.agent, refresh=args.refresh,
        )
    else:
        from pageviews_api import fetch_per_article
        result = fetch_per_article(
            args.lang, args.article, start, end,
            granularity=args.granularity, access=args.access, agent=args.agent,
            refresh=args.refresh,
        )

    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result.get("exists"):
        print(f"\nNOTE: no pageviews data found for '{args.article}' on {args.lang}.wikipedia "
              f"in range {start}-{end} (article may not exist in this edition, or is newer).",
              file=sys.stderr)
