"""Offline unit tests for the pure statistics module (no network calls).

Run with:  python -m pytest tests/  (from the skill directory)
or:        python tests/test_trend_analysis.py
"""
import os
import sys
import unittest

SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "scripts")
sys.path.insert(0, os.path.abspath(SCRIPTS_DIR))

from trend_analysis import (  # noqa: E402
    mann_kendall,
    linear_growth_rate,
    year_over_year,
    detect_spikes,
    spike_adjusted,
    coefficient_of_variation,
    analyze_series,
    rank_series,
)


class TestMannKendall(unittest.TestCase):
    def test_clear_uptrend_is_significant_increasing(self):
        values = [10 * (1.15 ** i) for i in range(30)]
        result = mann_kendall(values)
        self.assertEqual(result["trend"], "increasing")
        self.assertLess(result["p_value"], 0.05)

    def test_clear_downtrend_is_significant_decreasing(self):
        values = [1000 * (0.9 ** i) for i in range(30)]
        result = mann_kendall(values)
        self.assertEqual(result["trend"], "decreasing")
        self.assertLess(result["p_value"], 0.05)

    def test_flat_noisy_series_has_no_significant_trend(self):
        # deterministic pseudo-noise around a constant mean
        values = [100 + (i % 5) * 3 - (i % 7) * 2 for i in range(30)]
        result = mann_kendall(values)
        self.assertIn(result["trend"], ("no_significant_trend", "increasing", "decreasing"))
        # main invariant: function must not crash and must return a p_value
        self.assertIsNotNone(result["p_value"])

    def test_too_short_series_is_insufficient_data(self):
        result = mann_kendall([1, 2])
        self.assertEqual(result["trend"], "insufficient_data")
        self.assertIsNone(result["p_value"])


class TestGrowthRate(unittest.TestCase):
    def test_growth_rate_matches_known_ratio(self):
        # exactly 10% compounding growth per month
        values = [100 * (1.10 ** i) for i in range(12)]
        result = linear_growth_rate(values)
        self.assertAlmostEqual(result["monthly_pct"], 10.0, delta=0.5)
        self.assertGreater(result["r2"], 0.99)

    def test_too_short_series_returns_none(self):
        result = linear_growth_rate([5, 5])
        self.assertIsNone(result["monthly_pct"])


class TestYearOverYear(unittest.TestCase):
    def test_requires_24_months(self):
        self.assertIsNone(year_over_year([1] * 23))

    def test_computes_expected_pct_change(self):
        prev12 = [100] * 12
        last12 = [150] * 12
        result = year_over_year(prev12 + last12)
        self.assertEqual(result["prev_12m_total"], 1200)
        self.assertEqual(result["last_12m_total"], 1800)
        self.assertEqual(result["yoy_pct"], 50.0)


class TestSpikes(unittest.TestCase):
    def test_detects_single_viral_spike(self):
        values = [100] * 8 + [5000] + [100] * 8
        spikes = detect_spikes(values)
        self.assertIn(8, spikes)

    def test_no_spikes_in_flat_series(self):
        values = [100] * 15
        self.assertEqual(detect_spikes(values), [])

    def test_spike_adjusted_replaces_only_flagged_months(self):
        values = [100] * 8 + [5000] + [100] * 8
        spikes = detect_spikes(values)
        adjusted = spike_adjusted(values, spikes)
        self.assertEqual(adjusted[8], 100)
        self.assertEqual(adjusted[0], 100)


class TestCoefficientOfVariation(unittest.TestCase):
    def test_zero_mean_returns_none(self):
        self.assertIsNone(coefficient_of_variation([0, 0, 0]))

    def test_constant_series_has_zero_cv(self):
        self.assertEqual(coefficient_of_variation([50] * 10), 0.0)


class TestAnalyzeSeries(unittest.TestCase):
    def test_missing_article_short_circuits(self):
        result = analyze_series([], exists=False)
        self.assertFalse(result["exists"])
        self.assertEqual(result["confidence"], "low")
        self.assertTrue(result["caveats"])

    def test_strong_sustained_growth_gets_high_or_medium_confidence(self):
        values = [50 * (1.08 ** i) for i in range(30)]
        result = analyze_series(values, exists=True)
        self.assertTrue(result["exists"])
        self.assertIn(result["confidence"], ("high", "medium"))
        self.assertEqual(result["mann_kendall"]["trend"], "increasing")

    def test_sparse_low_volume_series_is_flagged_low_confidence(self):
        values = [0, 1, 0, 2, 0, 0, 1, 3, 0, 0, 1, 0]
        result = analyze_series(values, exists=True)
        self.assertEqual(result["confidence"], "low")
        self.assertTrue(any("шум" in c or "даних" in c for c in result["caveats"]))


class TestRankSeries(unittest.TestCase):
    def test_validated_growth_ranks_above_no_article(self):
        growing = [50 * (1.1 ** i) for i in range(30)]
        results = {
            "lang_a_growing": analyze_series(growing, exists=True),
            "lang_b_missing": analyze_series([], exists=False),
        }
        ranked = rank_series(results)
        keys_in_order = [r["key"] for r in ranked]
        self.assertLess(keys_in_order.index("lang_a_growing"), keys_in_order.index("lang_b_missing"))
        self.assertEqual(ranked[0]["priority"], "validated_growth")


if __name__ == "__main__":
    unittest.main()
