---
name: wikipedia-trends
description: >-
  Analyze Wikipedia pageview trends across languages to gauge audience
  interest in a topic for B2C product decisions (which course/topic to build
  next, which language to localize into). Fetches real Wikimedia Pageviews
  API data, resolves a free-text topic to the correct article per language
  via Wikidata, computes growth rate / year-over-year change / statistical
  significance / spike detection, rates how trustworthy the trend is, and
  produces a comparison chart plus a shareable one-page PDF report. Use when
  the user asks to compare interest in a topic across Wikipedia languages,
  check if interest in a topic is growing, or decide which
  language/audience/topic to invest in next based on Wikipedia data.
---

# Wikipedia Trends

Turns a plain-language question ("is interest in X growing in language Y?",
"compare X across languages A/B/C") into real Wikimedia pageview data, a
trend analysis with an explicit confidence rating, a chart, and a one-page
PDF report. All statistics are computed by the scripts, not by you — read
the script output and relay it, don't recompute numbers yourself.

## One-time setup (idempotent, run once per session)

```bash
cd <this-skill-directory>
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt
```

All commands below assume `PY=<this-skill-directory>/.venv/bin/python`.

## Step-by-step workflow

1. **Extract parameters from the request**: topic (free text), target
   language codes (Wikipedia codes: `en`, `pl`, `cs`, `uk`, `de`, `es`,
   `fr`, ...), time window (default 24 months if not stated — enough for
   one year-over-year comparison). If the user says "last two years" use
   `--months 24`; "since 2015" use `--start 20150101`.

2. **Run the single pipeline command**:

   ```bash
   $PY scripts/wiki_trends.py run --topic "intermittent fasting" --langs pl,cs --months 24 --out reports/if_pl_cs
   ```

   This resolves the topic on Wikidata, fetches pageviews per language,
   analyzes each series, and writes `reports/if_pl_cs.png` (chart) and
   `reports/if_pl_cs.pdf` (one-page report). It prints a complete
   human-readable summary to stdout — **read that summary, it already has
   the numbers, the confidence rating and the caveats you need.**

3. **Verify the topic resolution before trusting the numbers.** The stdout
   summary prints the resolved Wikidata item id + label + description
   (e.g. `Q1666254 (intermittent fasting)`). If it looks wrong for what the
   user meant, don't proceed with those numbers — re-run with an explicit
   `--qid` (see `resolve` subcommand to search candidates) or bypass
   resolution entirely with `--articles`.

4. **Always report, in your own words, at minimum:**
   - the direction and size of the trend per language (from `growth` /
     `year_over_year` fields — already computed, don't re-derive),
   - the **confidence rating** (`low` / `medium` / `high`) and **why**
     (relay the `caveats` list — they are already written as plain
     sentences),
   - the standing methodology note: pageviews measure *interest/attention*,
     not willingness to pay — a leading indicator to validate further, not
     a decision by itself,
   - if any language has `NO DATA`: that means no article exists in that
     edition (per Wikidata), **not** confirmed zero interest — say so.

5. **Show the chart inline** using the PNG path printed at the end
   (`![chart](reports/if_pl_cs.png)`), and mention the PDF path so the user
   can share it.

6. **Follow-up / related requests reuse cached data automatically** — raw
   API responses are cached under `data/cache/` for 7 days (pageviews) and
   30 days (Wikidata lookups). If the user changes languages, time window,
   or asks a related topic, just re-run `run` with the new parameters; only
   truly new (language, article, date-range) combinations hit the network.
   Use `--refresh` only if the user explicitly wants fresh data.

## Handling ambiguity and edge cases

| Situation | What to do |
|---|---|
| Topic resolves to the wrong Wikidata concept | Run `resolve` subcommand to see candidates, pick the right `--qid`, re-run `run --qid Q...` |
| You (or the user) already know exact article titles | Skip resolution: `run --articles "pl:Głodówka przerywana,cs:Přerušovaný půst" --langs pl,cs` (no `--topic` needed) |
| One language has no article | Reported as `NO DATA` with an explicit caveat — mention it, suggest checking manually whether the topic is just undocumented in that language before concluding "no audience" |
| User asks "how much can I trust this?" | Point to `confidence` + `caveats` fields — never invent a trust level yourself |
| User asks about > ~6 languages/topics at once | Run in batches (2-3 series at a time keeps the chart/PDF readable); mention this limit to the user |
| HTTP 429 from Wikimedia | The scripts already retry with backoff; if it still fails, wait a few seconds and re-run the same command (cache will skip anything already fetched) |
| Question is really "which audience/topic should we explore next" | The stdout summary already prints a **ranked recommendation** section (`rank_series` in `trend_analysis.py`) — relay it, it's grounded in the same numbers |

## Subcommands (for narrower/manual control)

- `resolve --topic "..." --langs a,b,c [--pivot-lang en]` — inspect topic→Wikidata→titles mapping only.
- `fetch --lang xx --article "Exact Title" --months 24` — fetch one series only.
- `analyze --data-file path.json` — stats for one already-fetched series.
- `run ...` — full pipeline (the one you'll use almost always).

Run `$PY scripts/wiki_trends.py <subcommand> --help` for full flag lists.

## More detail

- [reference.md](reference.md) — data source details, the statistics/heuristics used (Mann-Kendall trend test, spike detection, confidence scoring), and known limitations.
- [examples.md](examples.md) — worked examples for the three sample questions from the assignment brief, with the exact commands used.
