"""Pure statistics on a monthly pageviews series. No network calls here on
purpose, so this module is trivial to unit test (see tests/).

All functions take/return plain dicts and lists so they are easy for an
agent (or a human) to inspect as JSON.
"""
from __future__ import annotations

import math

import numpy as np


def mann_kendall(values: list[float]) -> dict:
    """Non-parametric trend test. Returns direction + two-sided p-value.

    S = sum of sign(x_j - x_i) for all i<j. Under H0 (no trend), S is
    approximately normal for n>=~10, which lets us get a p-value without
    needing scipy.
    """
    n = len(values)
    if n < 4:
        return {"trend": "insufficient_data", "p_value": None, "s": None}
    s = 0
    for i in range(n - 1):
        for j in range(i + 1, n):
            diff = values[j] - values[i]
            s += (diff > 0) - (diff < 0)
    var_s = n * (n - 1) * (2 * n + 5) / 18
    if s > 0:
        z = (s - 1) / math.sqrt(var_s)
    elif s < 0:
        z = (s + 1) / math.sqrt(var_s)
    else:
        z = 0.0
    p_value = 2 * (1 - _norm_cdf(abs(z)))
    if p_value < 0.05:
        trend = "increasing" if s > 0 else "decreasing"
    else:
        trend = "no_significant_trend"
    return {"trend": trend, "p_value": round(p_value, 4), "s": s, "z": round(z, 3)}


def _norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def linear_growth_rate(values: list[float]) -> dict:
    """Fit log1p(views) ~ month_index to get an approximate compounding
    monthly growth rate, robust to the series containing zeros."""
    n = len(values)
    if n < 3:
        return {"monthly_pct": None, "annualized_pct": None, "r2": None}
    x = np.arange(n)
    y = np.log1p(np.array(values, dtype=float))
    slope, intercept = np.polyfit(x, y, 1)
    y_pred = slope * x + intercept
    ss_res = float(np.sum((y - y_pred) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
    monthly_pct = (math.exp(slope) - 1) * 100
    annualized_pct = (math.exp(slope * 12) - 1) * 100
    return {
        "monthly_pct": round(monthly_pct, 2),
        "annualized_pct": round(annualized_pct, 2),
        "r2": round(r2, 3),
    }


def year_over_year(values: list[float]) -> dict | None:
    """Compare the most recent 12 months to the 12 months before that.
    Returns None if fewer than 24 months of data are available."""
    n = len(values)
    if n < 24:
        return None
    last12 = sum(values[-12:])
    prev12 = sum(values[-24:-12])
    if prev12 == 0:
        pct = None
    else:
        pct = round((last12 - prev12) / prev12 * 100, 1)
    return {"last_12m_total": int(last12), "prev_12m_total": int(prev12), "yoy_pct": pct}


def detect_spikes(values: list[float], window: int = 6, factor: float = 3.0) -> list[int]:
    """Return indices whose value exceeds `factor` x the trailing median of
    the previous `window` months (a simple viral-spike / news-event flag)."""
    spikes = []
    for i in range(len(values)):
        lo = max(0, i - window)
        trailing = values[lo:i]
        if len(trailing) < 3:
            continue
        med = float(np.median(trailing))
        if med > 0 and values[i] > factor * med:
            spikes.append(i)
    return spikes


def spike_adjusted(values: list[float], spikes: list[int], window: int = 6) -> list[float]:
    adjusted = list(values)
    for i in spikes:
        lo = max(0, i - window)
        trailing = [v for j, v in enumerate(values[lo:i])]
        adjusted[i] = float(np.median(trailing)) if trailing else values[i]
    return adjusted


def coefficient_of_variation(values: list[float]) -> float | None:
    arr = np.array(values, dtype=float)
    mean = arr.mean()
    if mean == 0:
        return None
    return round(float(arr.std()) / float(mean), 3)


def confidence_rating(n_months: int, avg_views: float, mk: dict, cv: float | None,
                       trend_agrees_without_spikes: bool | None) -> tuple[str, list[str]]:
    """Heuristic confidence tag + human-readable caveats, so a small/cheap
    agent model doesn't have to reason about statistics itself — it can
    just relay these strings."""
    caveats: list[str] = []
    score = 0

    if n_months >= 24:
        score += 1
    else:
        caveats.append(
            f"Лише {n_months} міс. даних (< 24) — надійне річне (YoY) порівняння недоступне або нестабільне."
        )

    if avg_views >= 500:
        score += 1
    elif avg_views < 50:
        caveats.append(
            f"Дуже мала середня кількість переглядів на місяць (~{avg_views:.0f}) — "
            "випадковий шум може домінувати над реальним трендом."
        )

    if mk["trend"] != "no_significant_trend" and mk["p_value"] is not None:
        score += 1
    else:
        caveats.append(
            f"Тест Манна-Кендалла не підтверджує статистично значущий тренд (p={mk['p_value']})."
        )

    if cv is not None and cv < 1.2:
        score += 1
    elif cv is not None:
        caveats.append(f"Висока варіативність між місяцями (CV={cv}) — тренд нестабільний.")

    if trend_agrees_without_spikes is False:
        caveats.append(
            "Виявлені стрибки переглядів (можлива вірусна подія чи новина): "
            "без них напрям тренду змінюється — зростання може бути одноразовим, а не стійким."
        )
    elif trend_agrees_without_spikes is True:
        score += 0.5

    if score >= 3.5:
        rating = "high"
    elif score >= 2:
        rating = "medium"
    else:
        rating = "low"
    return rating, caveats


def analyze_series(monthly_views: list[int], exists: bool) -> dict:
    """Full analysis for one language/article series (list of ints, oldest
    to newest, dense/no gaps)."""
    if not exists:
        return {
            "exists": False,
            "caveats": [
                "Немає статті / даних переглядів у цьому мовному розділі за цей період — "
                "це НЕ підтверджений нульовий інтерес, радше відсутність або надто нова стаття."
            ],
            "confidence": "low",
        }

    n = len(monthly_views)
    avg = float(np.mean(monthly_views)) if n else 0.0
    total = int(sum(monthly_views))
    mk = mann_kendall(monthly_views)
    growth = linear_growth_rate(monthly_views)
    yoy = year_over_year(monthly_views)
    cv = coefficient_of_variation(monthly_views)
    spikes = detect_spikes(monthly_views)
    trend_agrees = None
    growth_no_spikes = None
    if spikes:
        adjusted = spike_adjusted(monthly_views, spikes)
        growth_no_spikes = linear_growth_rate(adjusted)
        if growth["monthly_pct"] is not None and growth_no_spikes["monthly_pct"] is not None:
            trend_agrees = (growth["monthly_pct"] >= 0) == (growth_no_spikes["monthly_pct"] >= 0)

    rating, caveats = confidence_rating(n, avg, mk, cv, trend_agrees)

    return {
        "exists": True,
        "n_months": n,
        "total_views": total,
        "avg_monthly_views": round(avg, 1),
        "mann_kendall": mk,
        "growth": growth,
        "growth_excluding_spikes": growth_no_spikes,
        "year_over_year": yoy,
        "coefficient_of_variation": cv,
        "spike_months_idx": spikes,
        "confidence": rating,
        "caveats": caveats,
    }


def rank_series(results: dict[str, dict]) -> list[dict]:
    """Rank languages/topics by "worth exploring next", grounded in the
    numbers already computed by analyze_series. Returns an ordered list of
    {key, priority, score, rationale}.

    Priority buckets (highest first):
      1. validated_growth   - significant increasing trend + medium/high confidence
      2. promising_low_data - positive growth but low confidence (needs more data)
      3. unclear             - no significant trend / mixed signal
      4. no_article          - article/data missing in that edition
      5. declining           - significant decreasing trend
    """
    ranked = []
    for key, r in results.items():
        if not r.get("exists", False):
            ranked.append({
                "key": key, "priority": "no_article", "score": -1,
                "rationale": f"{key}: немає статті в цьому мовному розділі — "
                             "перш ніж інвестувати, варто перевірити вручну, чи тема просто не написана, "
                             "чи справді немає аудиторії.",
            })
            continue
        mk_trend = r["mann_kendall"]["trend"]
        monthly_pct = (r.get("growth") or {}).get("monthly_pct")
        confidence = r.get("confidence", "low")
        if mk_trend == "increasing" and confidence in ("medium", "high"):
            score = 3 + (1 if confidence == "high" else 0)
            ranked.append({
                "key": key, "priority": "validated_growth", "score": score,
                "rationale": f"{key}: стійке зростання (~{monthly_pct}%/міс, p={r['mann_kendall']['p_value']}), "
                             f"довіра до тренду: {confidence}. Хороший кандидат для інвестиції зараз.",
            })
        elif mk_trend == "increasing" and confidence == "low":
            ranked.append({
                "key": key, "priority": "promising_low_data", "score": 1,
                "rationale": f"{key}: є ознаки зростання (~{monthly_pct}%/міс), але даних замало/шумно — "
                             "варто дослідити наступним, зібравши більше даних, перш ніж вкладати ресурси.",
            })
        elif mk_trend == "decreasing":
            ranked.append({
                "key": key, "priority": "declining", "score": -2,
                "rationale": f"{key}: значуще зниження інтересу (~{monthly_pct}%/міс, p={r['mann_kendall']['p_value']}).",
            })
        else:
            ranked.append({
                "key": key, "priority": "unclear", "score": 0,
                "rationale": f"{key}: тренд неоднозначний або статистично незначущий "
                             f"(p={r['mann_kendall']['p_value']}) — недостатньо підстав для рішення.",
            })
    ranked.sort(key=lambda x: x["score"], reverse=True)
    return ranked


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Analyze a monthly pageviews JSON file (from pageviews_fetch.py)")
    parser.add_argument("--data-file", required=True)
    args = parser.parse_args()

    with open(args.data_file, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    views = [pt["views"] for pt in data["series"]]
    result = analyze_series(views, data["exists"])
    result["project"] = data["project"]
    result["article"] = data["article"]
    print(json.dumps(result, ensure_ascii=False, indent=2))
