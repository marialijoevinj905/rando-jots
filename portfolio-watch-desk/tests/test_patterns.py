import unittest

from watchdesk.patterns import detect, detect_at, trend_before

from .helpers import bars, trend


def names(cs):
    return {p.name for p in detect_at(cs, len(cs) - 1)}


class Trend(unittest.TestCase):
    def test_trend_direction(self):
        self.assertEqual(trend_before(bars(trend(8, step=-2)), 8 - 1 + 1 - 1), "down")
        self.assertEqual(trend_before(bars(trend(8, step=2)), 7), "up")


class SingleBar(unittest.TestCase):
    def test_hammer_after_decline(self):
        cs = bars(trend(8, 100, -2) + [(84.0, 84.6, 80.0, 84.5)])
        self.assertIn("Hammer", names(cs))

    def test_same_shape_after_rally_is_hanging_man(self):
        cs = bars(trend(8, 100, 2) + [(116.0, 116.6, 112.0, 116.5)])
        n = names(cs)
        self.assertIn("Hanging Man", n)
        self.assertNotIn("Hammer", n)

    def test_shooting_star_after_rally(self):
        cs = bars(trend(8, 100, 2) + [(116.5, 120.5, 115.9, 116.0)])
        self.assertIn("Shooting Star", names(cs))

    def test_doji(self):
        cs = bars(trend(8, 100, 0.1) + [(101.0, 102.0, 100.0, 101.05)])
        self.assertIn("Doji", names(cs))

    def test_marubozu(self):
        cs = bars(trend(8, 100, 0.2) + [(101.6, 106.6, 101.6, 106.6)])
        self.assertIn("Bullish Marubozu", names(cs))


class TwoBar(unittest.TestCase):
    def test_bullish_engulfing(self):
        cs = bars(trend(8, 100, -2) + [(84.0, 84.3, 82.5, 83.0), (82.5, 85.6, 82.3, 85.5)])
        p = [x for x in detect_at(cs, len(cs) - 1) if x.name == "Bullish Engulfing"]
        self.assertTrue(p)
        self.assertEqual(p[0].direction, "bullish")
        self.assertEqual(p[0].strength, 3)

    def test_bearish_engulfing(self):
        cs = bars(trend(8, 100, 2) + [(116.0, 117.4, 115.8, 117.0), (117.5, 117.7, 114.6, 115.0)])
        self.assertIn("Bearish Engulfing", names(cs))

    def test_piercing_line(self):
        cs = bars(trend(8, 100, -2) + [(85.0, 85.2, 80.8, 81.0), (80.0, 84.0, 79.8, 83.8)])
        self.assertIn("Piercing Line", names(cs))


class ThreeBar(unittest.TestCase):
    def test_morning_star(self):
        cs = bars(trend(8, 100, -2) + [(85.0, 85.2, 79.8, 80.0), (79.5, 80.0, 78.8, 79.6), (80.0, 84.6, 79.9, 84.5)])
        self.assertIn("Morning Star", names(cs))

    def test_evening_star(self):
        cs = bars(trend(8, 100, 2) + [(115.0, 120.2, 114.8, 120.0), (120.5, 121.2, 120.0, 120.6), (120.0, 120.1, 115.4, 115.5)])
        self.assertIn("Evening Star", names(cs))

    def test_three_white_soldiers(self):
        cs = bars(trend(8, 100, 0.1) + [(101.0, 103.2, 100.9, 103.0), (102.0, 105.2, 101.9, 105.0), (104.0, 107.2, 103.9, 107.0)])
        self.assertIn("Three White Soldiers", names(cs))

    def test_three_black_crows(self):
        cs = bars(trend(8, 100, 0.1) + [(107.0, 107.1, 104.8, 105.0), (106.0, 106.1, 102.8, 103.0), (104.0, 104.1, 100.8, 101.0)])
        self.assertIn("Three Black Crows", names(cs))


class Detect(unittest.TestCase):
    def test_detect_returns_newest_first_and_only_recent(self):
        cs = bars(trend(8, 100, -2) + [(84.0, 84.6, 80.0, 84.5)] + trend(6, 85, 0.05))
        found = detect(cs, recent=3)
        self.assertNotIn("Hammer", {p.name for p in found})  # too old
        idx = [p.index for p in found]
        self.assertEqual(idx, sorted(idx, reverse=True))

    def test_quiet_market_has_no_reversal_patterns(self):
        cs = bars([(100.0, 101.0, 99.0, 100.5)] * 12)
        self.assertFalse([p for p in detect(cs) if p.direction != "neutral"])


if __name__ == "__main__":
    unittest.main()
