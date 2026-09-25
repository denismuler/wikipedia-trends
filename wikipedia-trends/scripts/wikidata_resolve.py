"""Resolve a free-text topic to a Wikidata item and per-language Wikipedia
article titles.

Why Wikidata and not a direct Wikipedia search per language: the same
concept has a different title in every language edition ("Intermittent
fasting" vs "Přerušovaný půst" vs "Переривчасте голодування"). Wikidata
items link ("sitelink") to the corresponding article in each language
edition, so resolving the topic once on Wikidata and then reading sitelinks
is the reliable way to get an apples-to-apples article per language.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field

from common import http_get_json, cache_get, cache_set

WIKIDATA_API = "https://www.wikidata.org/w/api.php"


@dataclass
class TopicResolution:
    query: str
    qid: str | None
    label: str | None
    description: str | None
    candidates: list[dict] = field(default_factory=list)
    titles: dict[str, str | None] = field(default_factory=dict)  # lang -> article title or None

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "qid": self.qid,
            "label": self.label,
            "description": self.description,
            "candidates": self.candidates,
            "titles": self.titles,
        }


def search_entities(topic: str, pivot_lang: str = "en", limit: int = 5) -> list[dict]:
    """Search Wikidata for entities matching a free-text topic."""
    cache_key = f"wbsearch:{pivot_lang}:{topic.lower()}:{limit}"
    cached = cache_get(cache_key, max_age_days=30)
    if cached is not None:
        return cached
    data = http_get_json(
        WIKIDATA_API,
        params={
            "action": "wbsearchentities",
            "search": topic,
            "language": pivot_lang,
            "format": "json",
            "limit": limit,
            "type": "item",
        },
    )
    results = [
        {
            "id": item["id"],
            "label": item.get("label", ""),
            "description": item.get("description", ""),
        }
        for item in data.get("search", [])
    ]
    cache_set(cache_key, results)
    return results


def get_sitelinks(qid: str, langs: list[str]) -> dict[str, str | None]:
    """Return {lang: article_title or None} for the given Wikidata item."""
    cache_key = f"sitelinks:{qid}"
    cached = cache_get(cache_key, max_age_days=30)
    if cached is None:
        data = http_get_json(
            WIKIDATA_API,
            params={
                "action": "wbgetentities",
                "ids": qid,
                "props": "sitelinks",
                "format": "json",
            },
        )
        entity = data.get("entities", {}).get(qid, {})
        sitelinks = entity.get("sitelinks", {})
        cached = {site: info["title"] for site, info in sitelinks.items()}
        cache_set(cache_key, cached)
    out: dict[str, str | None] = {}
    for lang in langs:
        out[lang] = cached.get(f"{lang}wiki")
    return out


def resolve_topic(topic: str, langs: list[str], pivot_lang: str = "en",
                   qid: str | None = None) -> TopicResolution:
    """Resolve a topic phrase to per-language article titles.

    If ``qid`` is given, skip the search step (use when the caller already
    knows the exact Wikidata item, e.g. from a previous resolve call).
    """
    candidates = search_entities(topic, pivot_lang=pivot_lang)
    chosen_qid = qid or (candidates[0]["id"] if candidates else None)
    label = description = None
    for c in candidates:
        if c["id"] == chosen_qid:
            label, description = c["label"], c["description"]
            break

    result = TopicResolution(
        query=topic, qid=chosen_qid, label=label, description=description,
        candidates=candidates,
    )
    if chosen_qid:
        result.titles = get_sitelinks(chosen_qid, langs)
    else:
        result.titles = {lang: None for lang in langs}
    return result


def normalize_title(lang: str, title: str) -> str:
    """Resolve redirects/canonical casing for an explicit article title the
    user supplied directly (bypassing Wikidata search)."""
    cache_key = f"normalize:{lang}:{title}"
    cached = cache_get(cache_key, max_age_days=30)
    if cached is not None:
        return cached
    url = f"https://{lang}.wikipedia.org/w/api.php"
    data = http_get_json(
        url,
        params={
            "action": "query",
            "titles": title,
            "redirects": 1,
            "format": "json",
        },
    )
    pages = data.get("query", {}).get("pages", {})
    normalized = title
    for page in pages.values():
        if "title" in page and "missing" not in page:
            normalized = page["title"]
    cache_set(cache_key, normalized)
    return normalized


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Resolve a topic to per-language Wikipedia titles")
    parser.add_argument("--topic", required=True)
    parser.add_argument("--langs", required=True, help="comma-separated language codes, e.g. pl,cs,uk")
    parser.add_argument("--pivot-lang", default="en")
    parser.add_argument("--qid", default=None, help="skip search, use this Wikidata QID directly")
    args = parser.parse_args()

    langs = [l.strip() for l in args.langs.split(",") if l.strip()]
    res = resolve_topic(args.topic, langs, pivot_lang=args.pivot_lang, qid=args.qid)
    print(json.dumps(res.to_dict(), ensure_ascii=False, indent=2))

    missing = [l for l, t in res.titles.items() if t is None]
    if missing:
        print(f"\nNOTE: no Wikipedia article found for languages: {missing}", file=sys.stderr)
    if not res.qid:
        print("\nWARNING: could not resolve topic to any Wikidata item.", file=sys.stderr)
        sys.exit(1)
