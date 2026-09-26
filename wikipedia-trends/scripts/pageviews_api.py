"""Wikimedia Analytics API — Page view analytics (REST v1).

Covers the endpoints listed under:
https://doc.wikimedia.org/generated-data-platform/aqs/analytics-api/reference/page-views.html

Implemented on production ``wikimedia.org/api/rest_v1`` today:
  - per-article time series (monthly/daily; hourly where supported)
  - aggregate project time series (monthly/daily/hourly)
  - top articles for a project/month or day
  - top countries for a project/month (bucketed views — privacy)
  - legacy pagecounts aggregate (pre-2015-07)

Not available from Wikimedia (privacy / not deployed on REST v1):
  - pageviews for one article split by country
  - most-viewed articles for a single country
  - per-editor / top-edited-pages pageview metrics (documented in changelog; no public route found)
"""
from __future__ import annotations

from typing import Any
from urllib.parse import quote

from common import (
    aggregate_range_endpoints,
    cache_get,
    cache_set,
    day_range,
    http_get_json,
    month_range,
    project_domain,
    range_endpoints,
    wikipedia_lang_from_project,
)

PAGEVIEWS_BASE = "https://wikimedia.org/api/rest_v1/metrics/pageviews"
LEGACY_BASE = "https://wikimedia.org/api/rest_v1/metrics/legacy/pagecounts"
DATA_START = "20150701"

# Endpoints documented in the catalog but not callable on REST v1 (see module docstring).
UNSUPPORTED_CATALOG: dict[str, str] = {
    "per-article-by-country": (
        "Wikimedia does not expose per-article pageviews by country (reader privacy). "
        "Use top-by-country for whole-project traffic by country."
    ),
    "top-articles-by-country": (
        "No public REST v1 route found for “most-viewed pages for a country”. "
        "Use top (project-wide) or top-by-country (country totals for the project)."
    ),
    "per-editor": (
        "Per-editor pageview metrics are listed in the Analytics API changelog but are not "
        "available on wikimedia.org/api/rest_v1 in this environment (404 on all known paths)."
    ),
    "top-per-editor": (
        "Top pageviews for an editor’s edited pages are not available on REST v1 here."
    ),
}


def _encode_article(article: str) -> str:
    return quote(article.replace(" ", "_"), safe="")


def _get_cached_or_fetch(cache_key: str, url: str, refresh: bool, *,
                         treat_404_as_none: bool = False) -> Any:
    if not refresh:
        cached = cache_get(cache_key, max_age_days=7)
        if cached is not None:
            return cached
    data = http_get_json(url, treat_404_as_none=treat_404_as_none)
    if data is not None:
        cache_set(cache_key, data)
    return data


def fetch_per_article(
    lang: str,
    article: str,
    start: str,
    end: str,
    *,
    granularity: str = "monthly",
    access: str = "all-access",
    agent: str = "user",
    refresh: bool = False,
) -> dict:
    """Time series for one article (``exists`` + dense ``series`` for monthly/daily)."""
    project = project_domain(lang)
    start = max(start, DATA_START) if granularity == "monthly" else start
    api_start, api_end = range_endpoints(start, end, granularity)
    cache_key = (
        f"pv:article:{project}:{access}:{agent}:{article}:{granularity}:"
        f"{api_start}:{api_end}"
    )
    url = (
        f"{PAGEVIEWS_BASE}/per-article/{project}/{access}/{agent}/"
        f"{_encode_article(article)}/{granularity}/{api_start}/{api_end}"
    )
    data = _get_cached_or_fetch(cache_key, url, refresh, treat_404_as_none=True)

    series: list[dict[str, Any]] = []
    exists = data is not None and bool(data.get("items"))
    if granularity == "monthly":
        months = month_range(start, end)
        views_by = {m: 0 for m in months}
        if exists:
            for item in data["items"]:
                month = item["timestamp"][:6]
                if month in views_by:
                    views_by[month] += item["views"]
        series = [{"month": m, "views": views_by[m]} for m in months]
    elif granularity == "daily":
        days = day_range(start, end)
        views_by = {d: 0 for d in days}
        if exists:
            for item in data["items"]:
                day = item["timestamp"][:8]
                if day in views_by:
                    views_by[day] += item["views"]
        series = [{"day": d, "views": views_by[d]} for d in days]
    else:
        if exists:
            for item in data["items"]:
                series.append({
                    "timestamp": item["timestamp"],
                    "views": item["views"],
                })

    return {
        "endpoint": "per-article",
        "project": wikipedia_lang_from_project(project) + ".wikipedia",
        "article": article,
        "granularity": granularity,
        "access": access,
        "agent": agent,
        "start": api_start,
        "end": api_end,
        "exists": exists,
        "series": series,
        "raw": data,
    }


def _normalize_project(project: str) -> str:
    if project in ("all-projects", "all-wikipedia-projects"):
        return project
    return project_domain(project)


def fetch_aggregate(
    project: str,
    start: str,
    end: str,
    *,
    granularity: str = "monthly",
    access: str = "all-access",
    agent: str = "user",
    refresh: bool = False,
) -> dict:
    """Total pageviews for a project (or ``all-projects``)."""
    project = _normalize_project(project)
    api_start, api_end = aggregate_range_endpoints(start, end, granularity)
    cache_key = f"pv:agg:{project}:{access}:{agent}:{granularity}:{api_start}:{api_end}"
    url = (
        f"{PAGEVIEWS_BASE}/aggregate/{project}/{access}/{agent}/"
        f"{granularity}/{api_start}/{api_end}"
    )
    data = _get_cached_or_fetch(cache_key, url, refresh)
    items = (data or {}).get("items") or []
    series = [
        {"timestamp": it["timestamp"], "views": it["views"]}
        for it in items
    ]
    return {
        "endpoint": "aggregate",
        "project": project,
        "granularity": granularity,
        "access": access,
        "agent": agent,
        "start": api_start,
        "end": api_end,
        "series": series,
        "raw": data,
    }


def fetch_top_articles(
    project: str,
    year: str,
    month: str,
    day: str = "all-days",
    *,
    access: str = "all-access",
    limit: int | None = None,
    refresh: bool = False,
) -> dict:
    """Up to 1000 most-viewed articles for a project in a month or single day."""
    project = _normalize_project(project)
    year, month = year.zfill(4), month.zfill(2)
    cache_key = f"pv:top:{project}:{access}:{year}:{month}:{day}"
    url = f"{PAGEVIEWS_BASE}/top/{project}/{access}/{year}/{month}/{day}"
    data = _get_cached_or_fetch(cache_key, url, refresh)
    articles: list[dict] = []
    for block in (data or {}).get("items") or []:
        articles.extend(block.get("articles") or [])
    if limit is not None:
        articles = articles[:limit]
    return {
        "endpoint": "top",
        "project": project,
        "year": year,
        "month": month,
        "day": day,
        "access": access,
        "articles": articles,
        "raw": data,
    }


def fetch_top_by_country(
    project: str,
    year: str,
    month: str,
    *,
    access: str = "all-access",
    refresh: bool = False,
) -> dict:
    """Project pageviews by country for one month (bucketed ``views`` strings + ``views_ceil``)."""
    project = _normalize_project(project)
    year, month = year.zfill(4), month.zfill(2)
    cache_key = f"pv:topcountry:{project}:{access}:{year}:{month}"
    url = f"{PAGEVIEWS_BASE}/top-by-country/{project}/{access}/{year}/{month}"
    data = _get_cached_or_fetch(cache_key, url, refresh)
    countries: list[dict] = []
    for block in (data or {}).get("items") or []:
        countries.extend(block.get("countries") or [])
    return {
        "endpoint": "top-by-country",
        "project": project,
        "year": year,
        "month": month,
        "access": access,
        "countries": countries,
        "privacy_note": (
            "Country view counts are privacy-bucketed ranges, not exact integers. "
            "Use rank and views_ceil for comparisons."
        ),
        "raw": data,
    }


def fetch_legacy_pagecounts(
    project: str,
    start: str,
    end: str,
    *,
    granularity: str = "monthly",
    access_site: str = "all-sites",
    refresh: bool = False,
) -> dict:
    """Legacy pagecounts before 2015-07 (``/metrics/legacy/pagecounts/aggregate/…``)."""
    project = _normalize_project(project)
    api_start, api_end = aggregate_range_endpoints(start, end, granularity)
    cache_key = f"pv:legacy:{project}:{access_site}:{granularity}:{api_start}:{api_end}"
    url = (
        f"{LEGACY_BASE}/aggregate/{project}/{access_site}/"
        f"{granularity}/{api_start}/{api_end}"
    )
    data = _get_cached_or_fetch(cache_key, url, refresh)
    items = (data or {}).get("items") or []
    series = [
        {"timestamp": it["timestamp"], "count": it["count"]}
        for it in items
    ]
    return {
        "endpoint": "legacy-pagecounts",
        "project": project,
        "granularity": granularity,
        "access_site": access_site,
        "start": api_start,
        "end": api_end,
        "series": series,
        "raw": data,
    }


def unsupported_catalog_response(endpoint: str) -> dict:
    reason = UNSUPPORTED_CATALOG.get(endpoint, "Unknown or unsupported pageviews endpoint.")
    return {
        "endpoint": endpoint,
        "error": "unsupported",
        "message": reason,
        "docs": "https://doc.wikimedia.org/generated-data-platform/aqs/analytics-api/reference/page-views.html",
    }


# Backward-compatible alias used by pageviews_fetch.py
def fetch_pageviews(lang: str, article: str, start: str, end: str,
                    access: str = "all-access", agent: str = "user",
                    refresh: bool = False) -> dict:
    out = fetch_per_article(
        lang, article, start, end,
        granularity="monthly", access=access, agent=agent, refresh=refresh,
    )
    return {
        "project": out["project"],
        "article": out["article"],
        "start": max(start, DATA_START),
        "end": end,
        "exists": out["exists"],
        "series": out["series"],
    }
