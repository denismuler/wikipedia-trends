# Worked examples

Real runs against the three sample questions from the assignment brief.
`$PY` = `.venv/bin/python` inside this skill directory. Outputs referenced
here are checked into `examples_output/` for reference.

## 1. "Compare growth of interest in intermittent fasting between Polish and Czech Wikipedia over the last two years"

```bash
$PY scripts/wiki_trends.py run --topic "intermittent fasting" --langs pl,cs --months 24 --out examples_output/intermittent_fasting_pl_cs
```

What happened: the topic resolved to Wikidata `Q1666254` ("intermittent
fasting"). Polish Wikipedia has **no dedicated article** on this topic
(no `plwiki` sitelink) — reported as `NO DATA`, not zero interest. Czech
Wikipedia (`Přerušovaný půst`) has data: a significant **declining** trend
(Mann-Kendall p≈0.0, ~-6.7%/month), confidence `medium` (volume is on the
lower side, so the percentage should be read with the absolute counts
in mind). A viral spike is visible around one month in the chart, and the
report explicitly checks whether the trend still holds with that spike
removed.

Answering this out loud: "There's no dedicated Polish Wikipedia article on
intermittent fasting at all right now — that's more useful for you than a
number, since it means either no one's written about it yet or it's not a
distinct topic for Polish readers. On Czech Wikipedia there is an article,
but interest has been declining, not growing, over the last two years, and
that decline is statistically significant, not just noise. So on the
current evidence I would not prioritize either language for this topic."

## 2. "We're considering adding an astronomy course. Is interest growing in Ukrainian Wikipedia, and how much can we trust that?"

```bash
$PY scripts/wiki_trends.py run --topic astronomy --langs uk --months 36 --out examples_output/astronomy_uk
```

Resolved to Wikidata `Q333` ("astronomy"). Ukrainian Wikipedia article
`Астрономія` has 36 months of data, ~1,600 views/month average — high
enough volume for a reliable read. Confidence: `high`. Mann-Kendall trend:
significant **decreasing** (p≈0.0, ~-6.8%/month, YoY -56%).

Answering this out loud: "Interest in astronomy on Ukrainian Wikipedia has
been declining, and with 3 years of consistent, high-volume data the
statistics say this is a real pattern, not noise — confidence is high. I
would not treat this as a strong signal to prioritize an astronomy course
right now, at least not on this evidence alone; worth checking whether
that mirrors your own product's engagement data before deciding."

## 3. "We're building a language-learning app. Compare interest in learning English across the language editions we've picked and tell us which audiences to look into next."

```bash
$PY scripts/wiki_trends.py run --topic "English language" --langs de,fr,es,pl --months 24 --out examples_output/english_learning_multi
```

Resolved to Wikidata `Q1860` ("English"). All four editions have enough
volume for `high` confidence, and all four show a statistically
significant **declining** trend over the last 24 months (Wikipedia
pageviews broadly have been trending down site-wide as search/AI-assistant
traffic shifts elsewhere — worth sanity-checking this against a
topic you expect to be flat, or against site-wide totals, before reading
too much into any single topic's decline).

Answering this out loud: "None of the four editions show growing interest
in 'English (language)' as a Wikipedia topic over the last two years —
all four are declining, and all with enough data to trust that direction.
Given that, none of these four would be my first choice to prioritize
based on this signal alone. If you want a 'what to explore next' ranking
even when everything is currently declining, rerun with more/different
languages or a related seed topic (e.g. an exam name like TOEFL/IELTS,
which is a more app-relevant proxy than the general 'English language'
encyclopedia article) — the `rank_series` output in the pipeline will
re-rank as soon as one series shows validated growth."

## Notes for follow-up questions

- Changing the time window or adding a language re-runs `run` with new
  flags; already-fetched (language, article, date-range) combinations are
  served from cache (`data/cache/`), so this is fast and doesn't re-hit the
  API.
- If a topic phrase resolves to an unexpected Wikidata item, run
  `resolve --topic "..." --langs xx` first to see the candidate list, then
  pass the right `--qid` to `run`.
