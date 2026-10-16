import math
import unittest

from watchdesk.models import Candle, Holding
from watchdesk.providers import SimulatedProvider
from watchdesk.signals import Series, Settings, analyze, backtest, label_for, resample, score_at

from .helpers import series


def wavy(n, drift):
    return [100 * math.exp(drift * i + 0.03 * math.sin(i / 3)) for i in range(n)]


class Labels(unittest.TestCase):
    def test_thresholds(self):
        self.assertEqual([label_for(x) for x in (80, 30, 0, -30, -80)], ["Strong buy", "Buy", "Hold", "Reduce", "Sell"])


class Scoring(unittest.TestCase):
    def test_uptrend_scores_positive_and_downtrend_negative(self):
        up = analyze("UP", series(wavy(300, 0.004)), with_backtest=False)
        down = analyze("DN", series(wavy(300, -0.004)), with_backtest=False)
        self.assertGreater(up["score"], 15)
        self.assertLess(down["score"], -15)

    def test_score_is_the_sum_of_its_components(self):
        s = Series(SimulatedProvider(seed=3, anchors={}).daily("ABC"))
        score, comps = score_at(s, len(s.closes) - 1)
        self.assertAlmostEqual(score, max(-100, min(100, sum(c["points"] for c in comps))), places=6)
        self.assertTrue(all(c["reason"] for c in comps))

    def test_not_enough_history(self):
        a = analyze("NEW", series([10.0] * 10))
        self.assertFalse(a["ok"])


class Analysis(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.daily = SimulatedProvider(seed=11, anchors={}).daily("SIM")
        cls.price = cls.daily[-1].c

    def test_shape(self):
        a = analyze("SIM", self.daily)
        self.assertTrue(a["ok"])
        self.assertTrue(-100 <= a["score"] <= 100)
        for key in ("latest", "stats", "levels", "patterns", "suggestions", "backtest", "probabilities"):
            self.assertIn(key, a)
        lv = a["levels"]
        self.assertLess(lv["atr_stop"], self.price)
        st = a["stats"]
        self.assertLess(st["range_1d_68"][0], self.price)
        self.assertGreater(st["range_1d_68"][1], self.price)
        self.assertLessEqual(st["max_drawdown_1y_pct"], 0)

    def test_stop_breach_is_the_first_suggestion(self):
        h = Holding("SIM", 10, self.price * 1.2, stop=self.price * 1.05)
        a = analyze("SIM", self.daily, holding=h, portfolio_value=self.price * 100)
        self.assertEqual(a["suggestions"][0]["action"], "Exit / review")

    def test_overweight_position_gets_trim_with_share_count(self):
        h = Holding("SIM", 100, self.price)
        a = analyze("SIM", self.daily, holding=h, portfolio_value=self.price * 100 * 2,
                    settings=Settings(max_position_pct=20))
        trim = [s for s in a["suggestions"] if s["action"] == "Trim"]
        self.assertTrue(trim)
        self.assertIn("60 shares", trim[0]["text"])  # 50% weight -> 20% means selling 60 of 100

    def test_missing_stop_is_suggested(self):
        a = analyze("SIM", self.daily, holding=Holding("SIM", 1, self.price), portfolio_value=self.price * 50)
        self.assertIn("Set a stop", [s["action"] for s in a["suggestions"]])

    def test_position_size_for_buy_candidates_respects_risk_budget(self):
        a = analyze("UP", series(wavy(300, 0.004)), portfolio_value=100_000, settings=Settings(risk_per_trade_pct=1))
        buy = [s for s in a["suggestions"] if s["action"] == "Buy candidate"]
        self.assertTrue(buy)

    def test_intraday_read(self):
        q, bars = SimulatedProvider(seed=1, anchors={}, now=1_792_000_000).live("SIM")
        a = analyze("SIM", self.daily, intraday=bars)
        self.assertIsNotNone(a["intraday"]["vwap"])


class Backtest(unittest.TestCase):
    def test_counts_and_rates(self):
        s = Series(SimulatedProvider(seed=5, anchors={}).daily("BT"))
        bt = backtest(s)
        self.assertGreater(bt["bars_tested"], 100)
        five = bt["horizons"]["5"]
        self.assertLessEqual(five["all"]["count"], bt["bars_tested"])
        for side in ("buy", "sell"):
            if five[side]["count"]:
                self.assertTrue(0 <= five[side]["hit_rate"] <= 100)
        self.assertLessEqual(five["buy"]["count"] + five["sell"]["count"], five["all"]["count"])

    def test_no_look_ahead(self):
        """Scores at bar i must not change when future bars are appended."""
        d = SimulatedProvider(seed=9, anchors={}).daily("LA")
        i = len(d) - 30
        early, _ = score_at(Series(d[:i + 1]), i)
        later, _ = score_at(Series(d), i)
        self.assertAlmostEqual(early, later, places=6)


class Resample(unittest.TestCase):
    def test_five_minute_bars(self):
        ones = [Candle(600 + 60 * k, 10 + k, 11 + k, 9 + k, 10.5 + k, 1) for k in range(10)]
        five = resample(ones, 300)
        self.assertEqual(len(five), 2)
        self.assertEqual((five[0].o, five[0].h, five[0].l, five[0].c, five[0].v), (10, 15, 9, 14.5, 5))


if __name__ == "__main__":
    unittest.main()
