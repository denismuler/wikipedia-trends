#!/usr/bin/env python3
"""Single CLI entry point for the wikipedia-trends skill.

Subcommands (also usable standalone, see each script's --help):
  resolve  - topic phrase -> Wikidata item -> per-language article titles
  fetch    - one (lang, article) -> pageviews JSON (cached; monthly by default)
  query    - other Page view analytics endpoints (aggregate, top, top-by-country, legacy, …)
  analyze  - one pageviews JSON -> trend stats + confidence + caveats
  report   - N analyzed series -> comparison chart PNG + one-page PDF
  run      - full pipeline: resolve/fetch/analyze/report + human summary

Run `python scripts/wiki_trends.py run --help` for the common case.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from common import DATA_DIR, REPORTS_DIR, yyyymmdd, months_ago, ensure_dirs
from wikidata_resolve import resolve_topic, normalize_title
from pageviews_fetch import fetch_pageviews
from pageviews_api import (
    UNSUPPORTED_CATALOG,
    fetch_aggregate,
    fetch_legacy_pagecounts,
    fetch_per_article,
    fetch_top_articles,
    fetch_top_by_country,
    unsupported_catalog_response,
)
from trend_analysis import analyze_series, rank_series
from report_builder import build_pdf_report


def _parse_articles_override(raw: str) -> dict[str, str]:
    """'pl:Foo_bar,cs:Baz' -> {'pl': 'Foo bar', 'cs': 'Baz'}"""
    out = {}
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        lang, _, title = part.partition(":")
        out[lang.strip()] = title.strip().replace("_", " ")
    return out


def cmd_resolve(args: argparse.Namespace) -> None:
    langs = [l.strip() for l in args.langs.split(",") if l.strip()]
    res = resolve_topic(args.topic, langs, pivot_lang=args.pivot_lang, qid=args.qid)
    print(json.dumps(res.to_dict(), ensure_ascii=False, indent=2))


def cmd_fetch(args: argparse.Namespace) -> None:
    end = args.end or yyyymmdd(date.today())
    start = args.start or yyyymmdd(months_ago(args.months))
    if args.granularity == "monthly":
        result = fetch_pageviews(
            args.lang, args.article, start, end,
            access=args.access, agent=args.agent, refresh=args.refresh,
        )
    else:
        result = fetch_per_article(
            args.lang, args.article, start, end,
            granularity=args.granularity, access=args.access, agent=args.agent,
            refresh=args.refresh,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_query(args: argparse.Namespace) -> None:
    mode = args.mode
    if mode in UNSUPPORTED_CATALOG:
        print(json.dumps(unsupported_catalog_response(mode), ensure_ascii=False, indent=2))
        sys.exit(2)

    refresh = args.refresh
    if mode == "per-article":
        end = args.end or yyyymmdd(date.today())
        start = args.start or yyyymmdd(months_ago(args.months))
        if not args.lang or not args.article:
            print("ERROR: --lang and --article required for per-article", file=sys.stderr)
            sys.exit(1)
        result = fetch_per_article(
            args.lang, args.article, start, end,
            granularity=args.granularity, access=args.access, agent=args.agent,
            refresh=refresh,
        )
    elif mode == "aggregate":
        end = args.end or yyyymmdd(date.today())
        start = args.start or yyyymmdd(months_ago(args.months))
        project = args.project or (f"{args.lang}.wikipedia.org" if args.lang else None)
        if not project:
            print("ERROR: --project or --lang required for aggregate", file=sys.stderr)
            sys.exit(1)
        result = fetch_aggregate(
            project, start, end,
            granularity=args.granularity, access=args.access, agent=args.agent,
            refresh=refresh,
        )
    elif mode == "top":
        if not args.year or not args.month:
            print("ERROR: --year and --month required for top", file=sys.stderr)
            sys.exit(1)
        project = args.project or (f"{args.lang}.wikipedia.org" if args.lang else "en.wikipedia.org")
        result = fetch_top_articles(
            project, args.year, args.month, day=args.day,
            access=args.access, limit=args.limit, refresh=refresh,
        )
    elif mode == "top-by-country":
        if not args.year or not args.month:
            print("ERROR: --year and --month required for top-by-country", file=sys.stderr)
            sys.exit(1)
        project = args.project or (f"{args.lang}.wikipedia.org" if args.lang else "en.wikipedia.org")
        result = fetch_top_by_country(project, args.year, args.month, access=args.access, refresh=refresh)
    elif mode == "legacy-pagecounts":
        end = args.end or "2015070100"
        start = args.start or "2015010100"
        project = args.project or (f"{args.lang}.wikipedia.org" if args.lang else "en.wikipedia.org")
        result = fetch_legacy_pagecounts(
            project, start, end,
            granularity=args.granularity, access_site=args.access_site, refresh=refresh,
        )
    else:
        print(f"ERROR: unknown mode {mode}", file=sys.stderr)
        sys.exit(1)

    if not args.include_raw:
        result = {k: v for k, v in result.items() if k != "raw"}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    _print_query_summary(result)


def cmd_analyze(args: argparse.Namespace) -> None:
    with open(args.data_file, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    views = [pt["views"] for pt in data["series"]]
    result = analyze_series(views, data["exists"])
    result["project"], result["article"] = data["project"], data["article"]
    print(json.dumps(result, ensure_ascii=False, indent=2))


def _series_and_analysis(lang: str, article: str, start: str, end: str, refresh: bool):
    data = fetch_pageviews(lang, article, start, end, refresh=refresh)
    views = [pt["views"] for pt in data["series"]]
    months = [pt["month"] for pt in data["series"]]
    analysis = analyze_series(views, data["exists"])
    analysis["project"], analysis["article"] = data["project"], data["article"]
    return {"months": months, "views": views}, analysis


def cmd_run(args: argparse.Namespace) -> None:
    ensure_dirs()
    end = args.end or yyyymmdd(date.today())
    start = args.start or yyyymmdd(months_ago(args.months))
    langs = [l.strip() for l in args.langs.split(",") if l.strip()]

    overrides = _parse_articles_override(args.articles) if args.articles else {}
    titles: dict[str, str | None] = {}
    resolution = None

    if args.topic:
        resolution = resolve_topic(args.topic, langs, pivot_lang=args.pivot_lang, qid=args.qid)
        titles.update(resolution.titles)
    for lang, title in overrides.items():
        titles[lang] = normalize_title(lang, title)

    if not any(titles.get(l) for l in langs):
        print("ERROR: could not resolve any article for the requested languages. "
              "Try --qid with a specific Wikidata id, or pass --articles 'lang:Exact_Title' "
              "directly.", file=sys.stderr)
        sys.exit(1)

    series_map: dict[str, dict] = {}
    analyses: dict[str, dict] = {}
    for lang in langs:
        title = titles.get(lang)
        label = f"{lang}:{title}" if title else f"{lang}:(no article)"
        if not title:
            analyses[label] = {"exists": False, "caveats": [
                "Немає статті в цьому мовному розділі (за даними Wikidata) для цього запиту."
            ], "confidence": "low"}
            series_map[label] = {"months": [], "views": []}
            continue
        s, a = _series_and_analysis(lang, title, start, end, refresh=args.refresh)
        series_map[label] = s
        analyses[label] = a

    out_base = Path(args.out) if args.out else REPORTS_DIR / _slug(args.topic or "custom")
    out_png = out_base.with_suffix(".png")
    out_pdf = out_base.with_suffix(".pdf")
    topic_title = args.topic or ", ".join(f"{l}:{t}" for l, t in titles.items() if t)
    build_pdf_report(topic_title, series_map, analyses, out_pdf, normalize=not args.raw)
    # also drop a standalone PNG chart for inline display in chat
    from report_builder import build_comparison_chart
    build_comparison_chart(series_map, normalize=not args.raw, out_png=out_png)

    ranked = rank_series(analyses)
    print("=" * 70)
    print(f"WIKIPEDIA TRENDS REPORT: {topic_title}")
    if resolution and resolution.qid:
        print(f"Resolved Wikidata item: {resolution.qid} ({resolution.label}) — "
              f"{resolution.description}")
        print("VERIFY: check this matches the intended topic before trusting the numbers below.")
    print(f"Period: {start}–{end} · Languages: {', '.join(langs)}")
    print("-" * 70)
    for label, a in analyses.items():
        if not a.get("exists"):
            print(f"[{label}] NO DATA — {a['caveats'][0]}")
            continue
        g = a.get("growth") or {}
        yoy = a.get("year_over_year")
        yoy_str = f", YoY {yoy['yoy_pct']}%" if yoy and yoy.get("yoy_pct") is not None else ", YoY: n/a (<24mo)"
        print(f"[{label}] total={a['total_views']:,} avg/mo={a['avg_monthly_views']:.0f} "
              f"growth={g.get('monthly_pct')}%/mo (~{g.get('annualized_pct')}%/yr){yoy_str} "
              f"confidence={a['confidence']}")
        for c in a.get("caveats", []):
            print(f"    ! {c}")
    print("-" * 70)
    print("Ranked recommendation (what to explore next):")
    for r in ranked:
        print(f"  [{r['priority']}] {r['rationale']}")
    print("-" * 70)
    print(f"Chart: {out_png}")
    print(f"One-page PDF report: {out_pdf}")
    print("=" * 70)


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in text.lower()).strip("_")[:50]


def _print_query_summary(result: dict) -> None:
    ep = result.get("endpoint")
    if result.get("error") == "unsupported":
        print(result.get("message", ""), file=sys.stderr)
        return
    if ep == "top" and result.get("articles"):
        print("-" * 50, file=sys.stderr)
        for row in result["articles"][:10]:
            print(f"  #{row.get('rank')} {row.get('article')}: {row.get('views'):,} views", file=sys.stderr)
    elif ep == "top-by-country" and result.get("countries"):
        print("-" * 50, file=sys.stderr)
        print(result.get("privacy_note", ""), file=sys.stderr)
        for row in result["countries"][:10]:
            print(
                f"  #{row.get('rank')} {row.get('country')}: "
                f"{row.get('views')} (ceil≈{row.get('views_ceil')})",
                file=sys.stderr,
            )
    elif ep in ("aggregate", "legacy-pagecounts") and result.get("series"):
        pts = result["series"]
        key = "views" if ep == "aggregate" else "count"
        total = sum(p[key] for p in pts)
        print("-" * 50, file=sys.stderr)
        print(f"  {len(pts)} points, total {key}={total:,}", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="wiki_trends.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)

    p_resolve = sub.add_parser("resolve", help="topic -> per-language article titles")
    p_resolve.add_argument("--topic", required=True)
    p_resolve.add_argument("--langs", required=True)
    p_resolve.add_argument("--pivot-lang", default="en")
    p_resolve.add_argument("--qid", default=None)
    p_resolve.set_defaults(func=cmd_resolve)

    p_fetch = sub.add_parser("fetch", help="fetch monthly pageviews for one article")
    p_fetch.add_argument("--lang", required=True)
    p_fetch.add_argument("--article", required=True)
    p_fetch.add_argument("--months", type=int, default=24)
    p_fetch.add_argument("--start", default=None)
    p_fetch.add_argument("--end", default=None)
    p_fetch.add_argument("--granularity", default="monthly", choices=["monthly", "daily"])
    p_fetch.add_argument("--access", default="all-access")
    p_fetch.add_argument("--agent", default="user")
    p_fetch.add_argument("--refresh", action="store_true")
    p_fetch.set_defaults(func=cmd_fetch)

    query_modes = [
        "per-article", "aggregate", "top", "top-by-country", "legacy-pagecounts",
        "per-article-by-country", "top-articles-by-country", "per-editor", "top-per-editor",
    ]
    p_query = sub.add_parser(
        "query",
        help="Page view analytics API (see reference.md); use mode names from Wikimedia docs",
    )
    p_query.add_argument(
        "mode",
        choices=query_modes,
        help="endpoint family (unsupported modes print reason and exit 2)",
    )
    p_query.add_argument("--project", default=None, help="e.g. en.wikipedia.org or all-projects")
    p_query.add_argument("--lang", default=None, help="shorthand: builds {lang}.wikipedia.org")
    p_query.add_argument("--article", default=None)
    p_query.add_argument("--year", default=None)
    p_query.add_argument("--month", default=None)
    p_query.add_argument("--day", default="all-days", help="for top: DD or all-days")
    p_query.add_argument("--limit", type=int, default=None, help="trim top articles list")
    p_query.add_argument("--months", type=int, default=24)
    p_query.add_argument("--start", default=None)
    p_query.add_argument("--end", default=None)
    p_query.add_argument("--granularity", default="monthly", choices=["monthly", "daily", "hourly"])
    p_query.add_argument("--access", default="all-access")
    p_query.add_argument("--agent", default="user")
    p_query.add_argument("--access-site", default="all-sites", help="legacy-pagecounts only")
    p_query.add_argument("--refresh", action="store_true")
    p_query.add_argument("--include-raw", action="store_true", help="include full API payload in JSON")
    p_query.set_defaults(func=cmd_query)

    p_analyze = sub.add_parser("analyze", help="trend stats for one fetched series")
    p_analyze.add_argument("--data-file", required=True)
    p_analyze.set_defaults(func=cmd_analyze)

    p_run = sub.add_parser("run", help="full pipeline: resolve+fetch+analyze+report")
    p_run.add_argument("--topic", default=None, help="free-text topic, e.g. 'intermittent fasting'")
    p_run.add_argument("--langs", required=True, help="comma-separated Wikipedia language codes, e.g. pl,cs")
    p_run.add_argument("--pivot-lang", default="en")
    p_run.add_argument("--qid", default=None, help="skip topic search, use this exact Wikidata QID")
    p_run.add_argument("--articles", default=None,
                        help="override/skip resolution, e.g. 'pl:Głodówka przerywana,cs:Přerušovaný půst'")
    p_run.add_argument("--months", type=int, default=24)
    p_run.add_argument("--start", default=None, help="YYYYMMDD, overrides --months")
    p_run.add_argument("--end", default=None, help="YYYYMMDD, default today")
    p_run.add_argument("--out", default=None, help="output base path without extension")
    p_run.add_argument("--raw", action="store_true", help="plot raw view counts instead of normalized index")
    p_run.add_argument("--refresh", action="store_true", help="bypass local cache")
    p_run.set_defaults(func=cmd_run)

    return p


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
