"""Shared helpers: HTTP session, caching, date utilities.

No third-party state beyond `requests`. Kept dependency-light so the skill
stays easy to install and run on any machine (including inside an agent
sandbox driven by a small/cheap model).
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any

import requests

SKILL_DIR = Path(__file__).resolve().parent.parent
CACHE_DIR = SKILL_DIR / "data" / "cache"
DATA_DIR = SKILL_DIR / "data"
REPORTS_DIR = SKILL_DIR / "reports"

CONTACT = os.environ.get("WIKI_SKILL_CONTACT", "wikipedia-trends-skill/1.0")
USER_AGENT = f"wikipedia-trends-skill/1.0 ({CONTACT}) python-requests"

_session = requests.Session()
_session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})


class ApiError(RuntimeError):
    """Raised for any non-recoverable HTTP/API failure with a clear message."""


_MIN_INTERVAL = 0.4  # seconds between outgoing requests, be a polite API citizen
_last_request_ts = 0.0


def _throttle() -> None:
    global _last_request_ts
    wait = _MIN_INTERVAL - (time.time() - _last_request_ts)
    if wait > 0:
        time.sleep(wait)
    _last_request_ts = time.time()


def http_get_json(url: str, *, params: dict | None = None, retries: int = 5,
                   timeout: float = 15.0, treat_404_as_none: bool = False) -> Any:
    """GET a URL and parse JSON, with retry/backoff that honors 429 Retry-After.

    If ``treat_404_as_none`` is True, a 404 response returns ``None`` instead
    of raising (used by the pageviews API to mean "no data for this range").
    """
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            _throttle()
            resp = _session.get(url, params=params, timeout=timeout)
            if resp.status_code == 404 and treat_404_as_none:
                return None
            if resp.status_code == 429:
                retry_after = float(resp.headers.get("Retry-After", 2 ** (attempt + 1)))
                time.sleep(min(retry_after, 30))
                last_err = ApiError(f"429 rate limited on {url}")
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.HTTPError as exc:
            raise ApiError(f"HTTP {resp.status_code} calling {url}: {resp.text[:300]}") from exc
        except requests.RequestException as exc:
            last_err = exc
            time.sleep(1 + attempt)
    raise ApiError(f"Failed to reach {url} after {retries} attempts: {last_err}")


def ensure_dirs() -> None:
    for d in (CACHE_DIR, DATA_DIR, REPORTS_DIR):
        d.mkdir(parents=True, exist_ok=True)


def cache_path(key: str) -> Path:
    ensure_dirs()
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in key)[:60]
    return CACHE_DIR / f"{safe}_{digest}.json"

def cache_get(key: str, max_age_days: float | None = None) -> Any | None:
    path = cache_path(key)
    if not path.exists():
        return None
    if max_age_days is not None:
        age_days = (time.time() - path.stat().st_mtime) / 86400
        if age_days > max_age_days:
            return None
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def cache_set(key: str, value: Any) -> Path:
    path = cache_path(key)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(value, fh, ensure_ascii=False, indent=2)
    return path


def month_range(start: str, end: str) -> list[str]:
    """Return list of YYYYMM strings from start to end inclusive (both YYYYMMDD or YYYYMM)."""
    s = _to_first_of_month(start)
    e = _to_first_of_month(end)
    out = []
    cur = s
    while cur <= e:
        out.append(cur.strftime("%Y%m"))
        cur = _add_month(cur)
    return out


def _to_first_of_month(s: str) -> date:
    s = s.strip()
    if len(s) == 6:
        return datetime.strptime(s + "01", "%Y%m%d").date()
    if len(s) == 8:
        d = datetime.strptime(s, "%Y%m%d").date()
        return d.replace(day=1)
    raise ValueError(f"Expected YYYYMM or YYYYMMDD date, got {s!r}")


def _add_month(d: date) -> date:
    if d.month == 12:
        return d.replace(year=d.year + 1, month=1)
    return d.replace(month=d.month + 1)


def months_ago(n: int, from_date: date | None = None) -> date:
    d = from_date or date.today()
    d = d.replace(day=1)
    for _ in range(n):
        d = d.replace(day=1)
        if d.month == 1:
            d = d.replace(year=d.year - 1, month=12)
        else:
            d = d.replace(month=d.month - 1)
    return d


def yyyymmdd(d: date) -> str:
    return d.strftime("%Y%m%d")


def project_domain(lang_or_project: str) -> str:
    """Normalize a Wikipedia lang code or project string to ``{lang}.wikipedia.org``."""
    raw = lang_or_project.strip()
    if not raw:
        raise ValueError("empty project")
    if raw in ("all-projects", "all-wikipedia-projects"):
        return raw
    if raw.endswith(".wikipedia.org"):
        return raw
    if raw.endswith(".wikipedia"):
        return f"{raw}.org"
    if "." in raw:
        return raw if raw.endswith(".org") else raw
    return f"{raw}.wikipedia.org"


def wikipedia_lang_from_project(project: str) -> str:
    """``en.wikipedia.org`` or ``en.wikipedia`` -> ``en``."""
    base = project.replace(".wikipedia.org", "").replace(".wikipedia", "")
    return base.split(".")[0] if base else project


def day_range(start: str, end: str) -> list[str]:
    """Return YYYYMMDD strings from start to end inclusive (YYYYMMDD or YYYYMMDDHH)."""
    from datetime import timedelta

    s = _parse_yyyymmdd(start)
    e = _parse_yyyymmdd(end)
    out: list[str] = []
    cur = s
    while cur <= e:
        out.append(cur.strftime("%Y%m%d"))
        cur += timedelta(days=1)
    return out


def _parse_yyyymmdd(s: str) -> date:
    s = s.strip()
    if len(s) >= 8:
        return datetime.strptime(s[:8], "%Y%m%d").date()
    raise ValueError(f"Expected YYYYMMDD… date, got {s!r}")


def range_endpoints(start: str, end: str, granularity: str) -> tuple[str, str]:
    """Format start/end path segments for Wikimedia pageviews APIs."""
    g = granularity.lower()
    if g == "monthly":
        return _to_first_of_month(start).strftime("%Y%m%d"), _to_first_of_month(end).strftime("%Y%m%d")
    if g == "daily":
        return _parse_yyyymmdd(start).strftime("%Y%m%d"), _parse_yyyymmdd(end).strftime("%Y%m%d")
    if g == "hourly":
        return _pad_hour(start), _pad_hour(end)
    raise ValueError(f"unsupported granularity: {granularity}")


def aggregate_range_endpoints(start: str, end: str, granularity: str) -> tuple[str, str]:
    """Format start/end for ``/pageviews/aggregate/…`` (monthly/daily/hourly use YYYYMMDDHH)."""
    g = granularity.lower()
    if g == "monthly":
        s = _to_first_of_month(start).strftime("%Y%m%d") + "00"
        e = _to_first_of_month(end).strftime("%Y%m%d") + "00"
        return s, e
    if g == "daily":
        return _parse_yyyymmdd(start).strftime("%Y%m%d"), _parse_yyyymmdd(end).strftime("%Y%m%d")
    if g == "hourly":
        return _pad_hour(start), _pad_hour(end)
    raise ValueError(f"unsupported granularity: {granularity}")


def _pad_hour(s: str) -> str:
    s = s.strip()
    if len(s) == 10 and s.endswith("00"):
        return s
    if len(s) == 8:
        return s + "00"
    if len(s) >= 10:
        return s[:10]
    raise ValueError(f"Expected YYYYMMDD or YYYYMMDDHH, got {s!r}")
