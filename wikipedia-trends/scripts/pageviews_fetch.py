"""Fetch Wikipedia pageviews for one article from the Wikimedia REST API and
normalize the result into a dense monthly series (missing months = 0 views).

API docs: https://wikimedia.org/api/rest_v1/#/Pageviews%20data
Data only exists from 2015-07 onward. We always request ``agent=user`` to
exclude bots/spiders, which is the closest proxy to genuine human interest.
"""
from __future__ import annotations

import sys
from urllib.parse import quote

from common import http_get_json, cache_get, cache_set, month_range, yyyymmdd, months_ago

PAGEVIEWS_API = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article"
DATA_START = "20150701"  # earliest month with any per-article pageviews data


def fetch_pageviews(lang: str, article: str, start: str, end: str,
                     access: str = "all-access", agent: str = "user",
                     refresh: bool = False) -> dict:
    """Return a dict with a dense monthly series for one article.

    Result shape::

        {
          "project": "pl.wikipedia", "article": "...", "start": "20230101",
          "end": "20250101", "exists": true,
          "series": [{"month": "202301", "views": 123}, ...]
        }

    ``exists`` is False when the API has zero data for the whole range,
    which usually means the article does not exist in that language edition
    (or was created after ``end``) rather than genuinely zero interest.
    """
    project = f"{lang}.wikipedia"
    start = max(start, DATA_START)
    cache_key = f"pv:{project}:{access}:{agent}:{article}:{start}:{end}"
    if not refresh:
        cached = cache_get(cache_key, max_age_days=7)
        if cached is not None:
            return cached

    encoded_article = quote(article.replace(" ", "_"), safe="")
    url = f"{PAGEVIEWS_API}/{project}/{access}/{agent}/{encoded_article}/monthly/{start}/{end}"
    data = http_get_json(url, treat_404_as_none=True)

    months = month_range(start, end)
    views_by_month = {m: 0 for m in months}
    exists = data is not None and bool(data.get("items"))
    if exists:
        for item in data["items"]:
            # timestamp like "202301 0100" -> "YYYYMMDDHH"
            month = item["timestamp"][:6]
            if month in views_by_month:
                views_by_month[month] += item["views"]

    result = {
        "project": project,
        "article": article,
        "start": start,
        "end": end,
        "exists": exists,
        "series": [{"month": m, "views": views_by_month[m]} for m in months],
    }
    cache_set(cache_key, result)
    return result


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Fetch monthly Wikipedia pageviews for one article")
    parser.add_argument("--lang", required=True, help="Wikipedia language code, e.g. pl, cs, uk, en")
    parser.add_argument("--article", required=True, help="exact article title, spaces or underscores")
    parser.add_argument("--months", type=int, default=24, help="how many months back from today")
    parser.add_argument("--start", default=None, help="override: YYYYMMDD")
    parser.add_argument("--end", default=None, help="override: YYYYMMDD, default today")
    parser.add_argument("--refresh", action="store_true", help="bypass cache")
    args = parser.parse_args()

    end = args.end or yyyymmdd(__import__("datetime").date.today())
    start = args.start or yyyymmdd(months_ago(args.months))

    result = fetch_pageviews(args.lang, args.article, start, end, refresh=args.refresh)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["exists"]:
        print(f"\nNOTE: no pageviews data found for '{args.article}' on {args.lang}.wikipedia "
              f"in range {start}-{end} (article may not exist in this edition, or is newer).",
              file=sys.stderr)
