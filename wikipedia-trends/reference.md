# Reference

Detailed notes for when the summary in [SKILL.md](SKILL.md) isn't enough —
you generally shouldn't need to read this to answer a normal request.

## Data source

Official catalog: [Page view analytics](https://doc.wikimedia.org/generated-data-platform/aqs/analytics-api/reference/page-views.html)
(Wikimedia Analytics API, REST v1 at `https://wikimedia.org/api/rest_v1/metrics/pageviews/…`).

| Catalog item | CLI | Status |
|---|---|---|
| Pageviews for a page | `fetch` / `query per-article` | **Yes** — monthly (default) or daily; `run` uses monthly + `agent=user` |
| Project total pageviews | `query aggregate` | **Yes** — monthly/daily/hourly |
| Top articles | `query top` | **Yes** — month (`day=all-days`) or single day |
| Pageviews by country (project) | `query top-by-country` | **Yes** — bucketed ranges (`views_ceil` for rank) |
| Legacy pagecounts (pre-2015-07) | `query legacy-pagecounts` | **Yes** — `/metrics/legacy/pagecounts/aggregate/…` |
| Per-article by country | `query per-article-by-country` | **No** — not published (reader privacy) |
| Top articles for one country | `query top-articles-by-country` | **No** — no REST v1 route found |
| Editor edited-pages pageviews | `query per-editor` / `top-per-editor` | **No** — documented in changelog, not on REST v1 here |

- **Default trend pipeline** (`run`): per-article monthly,
  `access=all-access`, `agent=user`. Data from **2015-07** onward; `--start`
  before that is clamped for monthly article series.
- **Topic → article mapping**: [Wikidata](https://www.wikidata.org/w/api.php).
  `wbsearchentities` finds the best-matching item for a free-text topic in the
  pivot language; `wbgetentities` (props=sitelinks) reads the corresponding
  article title in each requested language edition (`{lang}wiki` sitelink).
  This is what lets "intermittent fasting" (en), "Přerušovaný půst" (cs) and
  "Переривчасте голодування" (uk) all be recognized as the same underlying
  topic instead of requiring the user to know each translated title.
- A missing sitelink for a language means **no dedicated article exists**
  in that Wikipedia edition — treated as `exists: False`, not as zero views.
- **Caching**: responses are cached to `data/cache/` as JSON
  (Wikidata: 30 days, pageviews: 7 days) so repeated/related questions in
  the same or later sessions don't re-hit the network unnecessarily. Use
  `--refresh` on `run`/`fetch` to force a live re-fetch.

## Statistics computed (`scripts/trend_analysis.py`, pure functions, unit-tested)

- **Monthly growth rate**: linear regression of `log1p(views)` on month
  index → converted back to an approximate compounding `%/month` and
  `%/year` rate, with `r2` (fit quality — low r2 means the "trend" is a
  rough average of a noisy series, not a clean pattern).
- **Year-over-year (YoY)**: sum of the last 12 months vs. the 12 months
  before that. Requires ≥24 months of data (returns `None` otherwise);
  chosen specifically because it cancels out seasonal patterns (e.g. a
  "back to school" topic peaking every September) that a raw slope would
  mistake for growth or decline.
- **Mann-Kendall trend test**: a non-parametric test for monotonic trend
  (implemented directly with `numpy`/`math.erf`, no `scipy` dependency).
  Gives a `p_value`; `p < 0.05` is treated as a statistically meaningful
  trend, otherwise the direction is reported as `no_significant_trend` —
  this is what stops a couple of noisy months from being over-read as "the
  topic is taking off."
- **Spike detection**: flags months where views exceed 3× the trailing
  6-month median (a simple heuristic for viral/news-driven traffic). The
  growth rate is recomputed on a spike-replaced series
  (`growth_excluding_spikes`); if the direction flips, that's surfaced as a
  caveat ("growth may be a one-off event, not sustained").
- **Coefficient of variation** (`std/mean`): flags generally noisy series.
- **Confidence rating** (`low`/`medium`/`high`): a simple additive score
  over (≥24 months of history, ≥500 avg monthly views, significant
  Mann-Kendall trend, CV < 1.2, spike-adjusted trend agrees with raw
  trend). This is intentionally simple and legible — every contributing
  reason is also emitted as a plain-language caveat string, so the rating
  is always explainable, not a black box.
- **Recommendation ranking** (`rank_series`): buckets each series into
  `validated_growth` (significant increasing trend + medium/high
  confidence) > `promising_low_data` (positive but low-confidence,
  i.e. worth collecting more data on) > `unclear` > `no_article` >
  `declining`, each with a one-line, numbers-grounded rationale.

## Known limitations (be upfront about these with the user)

- **Pageviews ≠ purchase intent.** This is a leading signal for "worth a
  deeper look", not a demand forecast. Always say so.
- **No per-article geography.** Use `query top-by-country` for
  *project-level* country mix, not for a single article. "Interest in
  language X" still means readers of X-language Wikipedia, not a country.
- **Article existence ≠ absence of interest.** No sitelink can mean the
  topic genuinely isn't of local interest, or simply that nobody has
  written the article yet. The skill always flags this rather than
  silently treating it as zero.
- **One search guess per topic.** `wbsearchentities` returns the top match
  for the pivot language; ambiguous topics (e.g. "Mercury") can resolve to
  the wrong concept. Always relay the resolved Wikidata id/description so
  the user (or you) can catch this, and use `--qid`/`--articles` to correct it.
- **Small samples are noisy.** Niche topics in smaller-language editions
  can have single-digit monthly views; the confidence rating flags this,
  but always mention absolute view counts, not just percentages (a jump
  from 3 to 9 views is "+200%" and meaningless).
