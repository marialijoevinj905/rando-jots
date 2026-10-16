import math
import unittest

from watchdesk import indicators as ind
from watchdesk.models import Candle
from watchdesk.signals import touch_probability

from .helpers import series

# Wilder's RSI worked example (StockCharts). Their 70.53 rounds the averages to 0.24 / 0.10 first;
# unrounded (avg gain 0.23857, avg loss 0.09979) it is 70.46.
RSI_CLOSES = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28]


class Averages(unittest.TestCase):
    def test_sma(self):
        self.assertEqual(ind.sma([1, 2, 3, 4, 5], 3), [None, None, 2.0, 3.0, 4.0])

    def test_ema_is_seeded_with_sma(self):
        e = ind.ema([1, 2, 3, 4, 5, 6], 3)
        self.assertEqual(e[:2], [None, None])
        self.assertAlmostEqual(e[2], 2.0)
        self.assertAlmostEqual(e[3], 3.0)  # 4*0.5 + 2*0.5
        self.assertAlmostEqual(e[5], 5.0)


class Momentum(unittest.TestCase):
    def test_rsi_matches_wilder_example(self):
        r = ind.rsi(RSI_CLOSES, 14)
        self.assertIsNone(r[13])
        self.assertAlmostEqual(r[14], 70.46, delta=0.01)

    def test_rsi_extremes(self):
        self.assertEqual(ind.rsi(list(range(1, 30)), 14)[-1], 100.0)
        self.assertLess(ind.rsi(list(range(30, 1, -1)), 14)[-1], 1.0)

    def test_macd_positive_in_uptrend(self):
        closes = [100 * 1.01 ** i for i in range(80)]
        line, sig, hist = ind.macd(closes)
        self.assertGreater(line[-1], 0)
        self.assertIsNotNone(sig[-1])
        self.assertAlmostEqual(hist[-1], line[-1] - sig[-1])
        self.assertIsNone(sig[30])  # signal needs 26 + 9 - 1 bars

    def test_stochastic_at_top_of_range(self):
        k, d = ind.stochastic(series([float(x) for x in range(1, 30)]))
        self.assertGreater(k[-1], 90)
        self.assertIsNotNone(d[-1])


class Volatility(unittest.TestCase):
    def test_bollinger_flat_series(self):
        mid, up, lo, pb, bw = ind.bollinger([10.0] * 25)
        self.assertEqual((mid[-1], up[-1], lo[-1], pb[-1], bw[-1]), (10.0, 10.0, 10.0, 0.5, 0.0))

    def test_atr_constant_range(self):
        cs = [Candle(i, 10, 11, 9, 10) for i in range(30)]
        self.assertAlmostEqual(ind.atr(cs, 14)[-1], 2.0)

    def test_true_range_uses_gap(self):
        cs = [Candle(0, 10, 10.5, 9.5, 10), Candle(1, 12, 12.5, 11.8, 12.2)]
        self.assertAlmostEqual(ind.true_range(cs)[1], 2.5)  # high - previous close

    def test_adx_strong_in_steady_trend(self):
        adx, pdi, mdi = ind.adx(series([100 + 2 * i for i in range(60)]))
        self.assertGreater(adx[-1], 25)
        self.assertGreater(pdi[-1], mdi[-1])


class Statistics(unittest.TestCase):
    def test_linreg_perfect_line(self):
        b, a, r2 = ind.linreg([3 + 2 * x for x in range(10)])
        self.assertAlmostEqual(b, 2)
        self.assertAlmostEqual(a, 3)
        self.assertAlmostEqual(r2, 1)

    def test_max_drawdown(self):
        self.assertAlmostEqual(ind.max_drawdown([100, 120, 90, 130, 117]), -25.0)

    def test_beta_of_itself_is_one(self):
        closes = [100 * math.exp(0.01 * math.sin(i)) for i in range(100)]
        self.assertAlmostEqual(ind.beta(closes, closes), 1.0)

    def test_beta_of_double_moves(self):
        bench = [100 * math.exp(0.01 * math.sin(i)) for i in range(100)]
        asset = [100 * math.exp(0.02 * math.sin(i)) for i in range(100)]
        self.assertAlmostEqual(ind.beta(asset, bench), 2.0, places=6)

    def test_zscore_and_vol(self):
        self.assertEqual(ind.zscore([5.0] * 20), 0.0)
        self.assertIsNone(ind.annualized_vol([1.0, 2.0]))

    def test_touch_probability(self):
        self.assertAlmostEqual(touch_probability(100, 100, 0.02, 20), 100.0)
        far = touch_probability(100, 200, 0.02, 20)
        near = touch_probability(100, 105, 0.02, 20)
        self.assertLess(far, 1)
        self.assertGreater(near, far)


class Levels(unittest.TestCase):
    def test_pivots(self):
        p = ind.pivot_points(Candle(0, 0, 110, 90, 100))
        self.assertAlmostEqual(p["P"], 100)
        self.assertAlmostEqual(p["R1"], 110)
        self.assertAlmostEqual(p["S1"], 90)
        self.assertAlmostEqual(p["R2"], 120)

    def test_fibonacci_up_swing(self):
        cs = series([100 + i for i in range(50)])
        f = ind.fibonacci(cs, 50)
        self.assertEqual(f["direction"], "up")
        span = f["swing_high"] - f["swing_low"]
        self.assertAlmostEqual(f["levels"]["50.0%"], f["swing_high"] - span / 2)

    def test_swing_levels_split_by_price(self):
        closes = [100, 104, 108, 104, 100, 96, 92, 96, 100, 104, 108, 104, 100, 98, 99, 100, 101]
        lv = ind.swing_levels(series([float(c) for c in closes]), width=2)
        price = closes[-1]
        self.assertTrue(all(x["level"] > price for x in lv["resistance"]))
        self.assertTrue(all(x["level"] < price for x in lv["support"]))
        self.assertTrue(lv["resistance"])


if __name__ == "__main__":
    unittest.main()
