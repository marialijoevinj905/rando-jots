from watchdesk.models import Candle

DAY = 86400
T0 = 1_760_000_000


def bars(ohlc, start=T0, step=DAY):
    """[(o, h, l, c), ...] -> candles, with volume 1e6."""
    return [Candle(start + i * step, o, h, l, c, 1e6) for i, (o, h, l, c) in enumerate(ohlc)]


def trend(n=8, start=100.0, step=-2.0):
    """A clean trend of n bars, each moving `step` with a modest body."""
    out, p = [], start
    for _ in range(n):
        o, c = p, p + step
        out.append((o, max(o, c) + 0.5, min(o, c) - 0.5, c))
        p = c
    return out


def series(closes, start=T0):
    return [Candle(start + i * DAY, c, c * 1.01, c * 0.99, c, 1e6) for i, c in enumerate(closes)]
