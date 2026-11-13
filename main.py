# Polymarket "Next CEO of NVIDIA?" forecaster (make.fun polymarket-nvidia-ceo-forecast-01).
#
# Design: empirical-quantile fan with recency-weighted windows.
#
# For each market, the trailing 720 minutes of 1-minute prices give the
# empirical distribution of price changes over h minutes, at anchor
# horizons [1, 5, 15, 30, 60, 120, 240]. Windows are weighted by recency
# (half-life 120 minutes: a market that just jumped is treated as hot,
# one that jumped hours ago is mostly forgotten). The forecast quantile
# at level tau and horizon h is
#     q_tau(h) = x + spread_tau(h),
# where x is the market's price at the checkpoint (persistence median)
# and spread_tau(h) is the empirical tau-quantile of h-minute changes
# minus its empirical median (so the fan's shape is the market's own:
# asymmetric, heavy-tailed), log-interpolated in h between anchors,
# scaled by 0.7, with a floor on the outer spreads so even a quiet
# market keeps some jump insurance.
#
# Why this shape: a uniform fan (the house baseline, sigma 0.0025) is far
# too wide for the quiet markets (most move ~0 in 4 hours) and far too
# narrow for the jumpy ones; per-market empirical quantiles fix both.
# Practice pinball loss 0.2857 vs the house baseline's 0.3636 (beats it on
# all six practice cases; the dev board's best is 0.256). Practice pays
# nothing and is no guide to the final, so the design is kept simple and
# robust rather than tuned to the last decimal: no drift, no trend, no
# cross-market normalisation (the sum of Yes prices wanders 0.81-1.09,
# so forcing it to a target does not help).
#
# Pure Python 3.13 standard library, deterministic, offline.
# Reads every <id>.in in the input directory (MAKEFUN_INPUT_DIR or /input)
# and writes <id>.out to the output directory (MAKEFUN_OUTPUT_DIR or /output).
# Output: {"forecasts": [{"id": <market id>, "q": [[q05,q25,q50,q75,q95] x 240]}]}.

import json
import math
import os
from pathlib import Path

INPUT_DIR = os.environ.get("MAKEFUN_INPUT_DIR", "/input")
OUTPUT_DIR = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")

QUANTILES = [0.05, 0.25, 0.5, 0.75, 0.95]
ANCHORS = [1, 5, 15, 30, 60, 120, 240]

LOOKBACK = 720        # minutes of trailing history per market
HALF_LIFE = 120.0     # recency half-life (minutes) for window weights
SPREAD_SCALE = 0.7    # shrink on the empirical spreads
SPREAD_FLOOR = 0.02   # min |outer spread| at h=240 (scales as sqrt(h/240))


def price6(x):
    """Clamp to [0, 1] and round to 6 decimals (0, never -0)."""
    return round(min(1.0, max(0.0, x)) * 1e6) / 1e6 + 0.0


def _weighted_quantile(pairs, p):
    """Quantile of (value, weight) pairs, sorted by value."""
    pairs = sorted(pairs)
    total = sum(w for _, w in pairs)
    if total <= 0:
        return 0.0
    acc = 0.0
    for v, w in pairs:
        acc += w
        if acc >= p * total:
            return v
    return pairs[-1][0]


def market_spreads(prices):
    """Per-anchor empirical quantile spreads of h-minute changes.

    Returns {anchor_h: [s05, s25, s50, s75, s95]} where each spread is the
    recency-weighted empirical tau-quantile of the h-minute change minus
    its weighted median, scaled by SPREAD_SCALE. Centring on the median
    (rather than on zero) keeps the fan's shape while the forecast median
    itself stays at the checkpoint price.
    """
    window = prices[-LOOKBACK:] if len(prices) > LOOKBACK else prices
    out = {}
    for h in ANCHORS:
        n_win = len(window) - h
        if n_win <= 0:
            out[h] = [0.0] * 5
            continue
        pairs = []
        for i in range(n_win):
            age = n_win - 1 - i  # minutes from this window's start to the last
            pairs.append((window[i + h] - window[i], 0.5 ** (age / HALF_LIFE)))
        med = _weighted_quantile(pairs, 0.5)
        out[h] = [(_weighted_quantile(pairs, t) - med) * SPREAD_SCALE for t in QUANTILES]
    return out


def _interp_spreads(spreads, h):
    """Log-linear interpolation of the five spreads at horizon h."""
    if h <= ANCHORS[0]:
        return spreads[ANCHORS[0]]
    if h >= ANCHORS[-1]:
        return spreads[ANCHORS[-1]]
    for a, b in zip(ANCHORS, ANCHORS[1:]):
        if a <= h <= b:
            f = (math.log(h) - math.log(a)) / (math.log(b) - math.log(a))
            sa, sb = spreads[a], spreads[b]
            return [sa[j] + f * (sb[j] - sa[j]) for j in range(5)]
    return spreads[ANCHORS[-1]]


def forecast_market(prices, horizon):
    """240 rows x 5 quantiles for one market, median at the checkpoint price."""
    x = prices[-1]
    spreads = market_spreads(prices)
    rows = []
    for h in range(1, horizon + 1):
        sp = _interp_spreads(spreads, h)
        fl = SPREAD_FLOOR * math.sqrt(h / 240.0)
        if abs(sp[0]) < fl:
            sp[0] = -fl
        if abs(sp[4]) < fl:
            sp[4] = fl
        row = [price6(x + sp[j]) for j in range(5)]
        for j in range(1, 5):
            if row[j] < row[j - 1]:
                row[j] = row[j - 1]
        rows.append(row)
    return rows


def forecast_case(case):
    horizon = case["horizon_minutes"]
    return [
        {"id": m["id"], "q": forecast_market(m["prices"], horizon)}
        for m in case["markets"]
    ]


def main():
    in_dir = Path(INPUT_DIR)
    out_dir = Path(OUTPUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    inputs = sorted(p.name for p in in_dir.iterdir() if p.name.endswith(".in"))
    for name in inputs:
        case_id = name[: -len(".in")]
        case = json.loads((in_dir / name).read_text(encoding="utf-8"))
        if list(case["quantiles"]) != QUANTILES:
            raise ValueError(f"{name} asks for quantiles {case['quantiles']}")
        forecasts = forecast_case(case)
        (out_dir / f"{case_id}.out").write_text(
            json.dumps({"forecasts": forecasts}) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
