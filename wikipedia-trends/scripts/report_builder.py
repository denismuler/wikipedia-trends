"""Build a chart (PNG) and a one-page shareable PDF report from analyzed
pageviews series. Uses only matplotlib (already a dependency for charts),
so no extra PDF library is required.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # headless-safe: no display needed
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime

from trend_analysis import rank_series

# ~90 chars fits A4 at 8pt with default side margins on 150 dpi export.
_BODY_WRAP = 92
_SUBTITLE = (
    "Джерело: Wikimedia Pageviews API (agent=user, all-access) · "
    "Перегляди статей ≠ готовність платити — це лише сигнал інтересу."
)


def _fill_lines(lines: list[str], width: int = _BODY_WRAP) -> str:
    blocks: list[str] = []
    for line in lines:
        if not line.strip():
            blocks.append("")
            continue
        blocks.append(
            textwrap.fill(
                line,
                width=width,
                break_long_words=False,
                break_on_hyphens=False,
            )
        )
    return "\n".join(blocks)


def _to_dates(months: list[str]) -> list[datetime]:
    return [datetime.strptime(m, "%Y%m") for m in months]


def build_comparison_chart(series_map: dict[str, dict], normalize: bool, out_png: Path) -> Path:
    """series_map: {label: {"months": [...], "views": [...]}}. If normalize,
    index each series to 100 at its first month so languages with very
    different absolute audience sizes are visually comparable."""
    fig, ax = plt.subplots(figsize=(8, 3.6), dpi=150)
    for label, s in series_map.items():
        if not s["months"]:
            continue
        months = _to_dates(s["months"])
        views = s["views"]
        if normalize:
            base = next((v for v in views if v > 0), None)
            y = [v / base * 100 for v in views] if base else views
        else:
            y = views
        ax.plot(months, y, marker="o", markersize=2.5, linewidth=1.6, label=label)
    ax.set_ylabel("Індекс (100 = перший місяць)" if normalize else "Перегляди / місяць")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax.legend(loc="upper left", fontsize=8, frameon=False)
    ax.grid(alpha=0.25)
    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png)
    plt.close(fig)
    return out_png


def build_pdf_report(topic: str, series_map: dict[str, dict], analyses: dict[str, dict],
                      out_pdf: Path, normalize: bool = True) -> Path:
    """One-page PDF: chart + key numbers + caveats + ranked recommendations."""
    ranked = rank_series(analyses)

    fig = plt.figure(figsize=(8.27, 11.69), dpi=150)  # A4 portrait
    gs = fig.add_gridspec(nrows=3, ncols=1, height_ratios=[0.13, 0.31, 0.56], hspace=0.32)
    fig.subplots_adjust(left=0.09, right=0.96, top=0.97, bottom=0.04)

    ax_title = fig.add_subplot(gs[0])
    ax_title.axis("off")
    ax_title.set_xlim(0, 1)
    ax_title.set_ylim(0, 1)
    title_lines = textwrap.fill(
        f"Wikipedia trends: {topic}",
        width=48,
        break_long_words=False,
        break_on_hyphens=False,
    )
    subtitle_lines = textwrap.fill(_SUBTITLE, width=_BODY_WRAP, break_long_words=False, break_on_hyphens=False)
    ax_title.text(
        0,
        1.0,
        title_lines,
        fontsize=16,
        weight="bold",
        va="top",
        ha="left",
        transform=ax_title.transAxes,
    )
    ax_title.text(
        0,
        0.72,
        subtitle_lines,
        fontsize=8,
        color="dimgray",
        va="top",
        ha="left",
        transform=ax_title.transAxes,
    )

    ax_chart = fig.add_subplot(gs[1])
    for label, s in series_map.items():
        if not s["months"]:
            continue
        months = _to_dates(s["months"])
        views = s["views"]
        y = views
        if normalize:
            base = next((v for v in views if v > 0), None)
            y = [v / base * 100 for v in views] if base else views
        ax_chart.plot(months, y, marker="o", markersize=2, linewidth=1.5, label=label)
    ax_chart.set_ylabel("Індекс (база=100)" if normalize else "Перегляди/міс")
    ax_chart.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax_chart.legend(loc="upper left", fontsize=8, frameon=False)
    ax_chart.grid(alpha=0.25)

    ax_text = fig.add_subplot(gs[2]); ax_text.axis("off")
    lines: list[str] = []
    lines.append("Ключові показники:")
    for label, a in analyses.items():
        if not a.get("exists"):
            lines.append(f"  • {label}: немає статті/даних у цьому розділі.")
            continue
        g = a.get("growth") or {}
        yoy = a.get("year_over_year")
        yoy_str = f", YoY {yoy['yoy_pct']}%" if yoy and yoy.get("yoy_pct") is not None else ""
        lines.append(
            f"  • {label}: ~{g.get('monthly_pct')}%/міс (~{g.get('annualized_pct')}%/рік){yoy_str}, "
            f"довіра: {a.get('confidence')}"
        )
    lines.append("")
    lines.append("Обмеження й припущення:")
    any_caveat = False
    for label, a in analyses.items():
        for c in a.get("caveats", []):
            lines.append(f"  • [{label}] {c}")
            any_caveat = True
    if not any_caveat:
        lines.append("  • Значних застережень не виявлено для наведених рядів.")
    lines.append("")
    lines.append("Що дослідити далі (за даними):")
    for r in ranked:
        lines.append(f"  • {r['rationale']}")

    ax_text.set_xlim(0, 1)
    ax_text.set_ylim(0, 1)
    ax_text.text(
        0,
        1.0,
        _fill_lines(lines),
        fontsize=8.3,
        va="top",
        ha="left",
        transform=ax_text.transAxes,
        family="monospace",
    )

    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_pdf)
    plt.close(fig)
    return out_pdf
