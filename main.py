# Polymarket "Next CEO of NVIDIA?" forecaster v3 (make.fun polymarket-nvidia-ceo-forecast-01).
#
# v3 rebuilds the entry on the top-10 reference architecture (a friend's
# grind, shared with us as a design reference -- prose only, this code is
# written from scratch here): a normal fan around a sum-reverting median,
# with per-market realised volatility, horizon-bucket calibration, a
# staleness shrink and an activity-tier widening, plus a skew correction
# on the upper-middle quantile.
#
# Design (all constants below are the reference v6 values):
#
# 1. MEDIAN = persistence + sum-reversion. The 24 candidates are mutually
#    exclusive, so the Yes prices should sum to ~1; each market's median
#    glides toward its normalised share x_i/S (S = sum of the last prices
#    of all markets in the case):
#        centre_i(h) = x_i + (1 - exp(-h/TAU)) * (x_i/S - x_i),  TAU = 180
#    The glide applies to the WHOLE fan (every quantile is centred on
#    centre_i(h)), not to the median alone.
#
# 2. SIGMA = realised vol per market, from 1-minute diffs. Diffs are
#    winsorised at +-0.05, then the root-mean-square over trailing windows
#    of 120 / 360 / 1440 minutes is blended 0.4 / 0.4 / 0.2. The blend is
#    floored at 0.0002 and capped at 0.012, then scaled by 0.47 (see the
#    "WHAT SHIPPED" note below for why). Fan half-width at horizon h:
#        width_j(h) = z_j * sigma * sqrt(h)          (z = normal quantiles)
#
# 3. HORIZON BUCKETS multiply the fan width: 1.0 for h 1-30, 0.85 for
#    h 31-120, 0.85 for h 121-240. The fan is too wide at long horizons;
#    short horizons stay full because jumps live there.
#
# 4. STALENESS: a market whose last price has not changed for >=120
#    minutes gets sigma x 0.5 (a dead market stays dead).
#
# 5. ACTIVITY TIER: the top tertile of markets by number of price changes
#    within the case gets sigma x 1.15. Active markets' moves cluster and
#    persist, so the fan is too narrow for them, not too wide.
#
# 6. QUANTILE OFFSETS (additive, after the width): (q05, q25, q50, q75,
#    q95) = (0, 0, 0, -0.04, +0.005). Realised prices skew below the fan
#    (q75 coverage was 0.841 vs 0.75 nominal), so the skew correction sits
#    on q75 -- NOT on the median (a median offset was rejected outright;
#    the centre is already right).
#
# Reference v6 practice loss (their true grader, same numbers as ours):
# mean 0.252411 (p00 0.384117, p01 0.301470, p02 0.333913, p03 0.254442,
# p04 0.189746, p05 0.105501; median error 0.748344, coverage90 0.913184).
# Our v1 (empirical fan, persistence median) is 0.285720 and our v2
# (empirical fan + price kernel + pooled blend) is 0.275400 on the same
# grader; this v3 is a different family, not a tweak of either.
#
# WHAT SHIPPED (this file) vs the reference v6 -- two changes, both
# measured on our grader and validated out-of-sample (see GRIND-V3.md):
#
# (a) SIGMA ESTIMATOR + CALIBRATION. The reference's prose says "realised
#     vol from 1-minute diffs" without naming the estimator. My first build
#     used RMS and landed at 0.290782 with cov90 0.9843 (fan far too wide)
#     while the median error matched the reference EXACTLY (0.748344), so
#     the centre was right and only the fan scale was wrong. Diagnosis: for
#     this steppy series RMS is dominated by rare jumps. Switching sigma to
#     the mean-absolute-diff estimator (normal-consistent, sqrt(pi/2)*E|d|)
#     reproduces the reference v6 almost exactly: 0.252634 (per-case within
#     0.0023, p04/p05/med_err exact). The SHIPPED estimator is RMS with a
#     global 0.47 calibration instead: practice 0.248893, and it ALSO wins
#     on 27 unseen pseudo-cases (0.933348 vs base 0.964917) and on the 15
#     final-like Nov-12 checkpoints (0.381742 vs 0.387870), with a positive
#     leave-one-out margin on every 5-case subset. The 0.47 sits mid-valley
#     (practice 0.2488 at 0.45, 0.2489 at 0.47, 0.2490 at 0.48, 0.2494 at
#     0.50 -- flat), not at a sharp argmin.
# (b) SIGMA FLOOR 0.0002 instead of 0.0004 (OAT winner, 4/6 cases, and the
#     0.0002-0.0003 valley is flat; 0.0008 is much worse).
# Everything else is the reference v6 unchanged (tau 180, buckets,
# staleness, activity tier, offsets).
#
# TESTED AND REJECTED on this family (details in GRIND-V3.md): pooled-sigma
# blend for short-history markets (practice +0.007, rejected); price-kernel
# sigma bw 0.075/0.10 (pseudo worse); tau 120 (practice -0.0005 but pseudo
# +0.049 -- a practice mirage, rejected); sigma cap 0.008 (practice gain
# concentrated in p03 alone, 1/6 wins; on the RMS champion it HURTS);
# winsor 0.08; bucket (1.0, 0.85, 0.75); q75 offsets -0.02/-0.03/-0.05/-0.06;
# q95 offset 0/+0.01; stale 0.4/0.6/off and thresholds 60/180; active
# 1.0/1.10/1.25; window-weight blends. The reference's own rejected levers
# (sub-diffusive beta, symmetric tail inflation, logit space, drift/momentum,
# bounce-reversal, jump-filtered sigma, burst window, per-quantile exponents)
# were NOT re-tested, per the reference.
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
# Standard-normal quantiles for QUANTILES (rounded to 9 dp; symmetric).
Z = [-1.644853627, -0.67448975, 0.0, 0.67448975, 1.644853627]

# --- reference v6 parameters (tunable via PARAMS for experiments) ---
PARAMS = {
    "tau": 180.0,            # sum-reversion glide time constant (minutes)
    "win_weights": ((120, 0.4), (360, 0.4), (1440, 0.2)),  # vol windows
    "winsor": 0.05,          # per-diff winsor cap
    "sigma_floor": 0.0002,
    "sigma_cap": 0.012,
    "buckets": ((30, 1.0), (120, 0.85), (240, 0.85)),  # (h_max, mult)
    "stale_minutes": 120,    # unchanged-price run that counts as stale
    "stale_mult": 0.5,
    "active_mult": 1.15,     # top-tertile activity widening
    "offsets": (0.0, 0.0, 0.0, -0.04, 0.005),
    "sigma_scale": 0.47,     # global calibration on sigma (see header note)
}


def price6(x):
    """Clamp to [0, 1] and round to 6 decimals (0, never -0)."""
    return round(min(1.0, max(0.0, x)) * 1e6) / 1e6 + 0.0


def _diffs(prices):
    """1-minute diffs of a price series."""
    return [prices[i + 1] - prices[i] for i in range(len(prices) - 1)]


def _sigma(prices, p):
    """Blended realised vol: RMS of winsorised 1-minute diffs over trailing
    windows of 120 / 360 / 1440 minutes, blended 0.4 / 0.4 / 0.2, floored
    at sigma_floor and capped at sigma_cap, then scaled by sigma_scale.
    """
    diffs = _diffs(prices)
    w = p["winsor"]
    win = [max(-w, min(w, d)) for d in diffs]
    if not win:
        return p["sigma_floor"]
    sig = 0.0
    for minutes, weight in p["win_weights"]:
        seg = win[-minutes:] if len(win) > minutes else win
        n = len(seg)
        var = sum(d * d for d in seg) / n
        sig += weight * math.sqrt(var)
    return min(max(sig, p["sigma_floor"]), p["sigma_cap"]) * p["sigma_scale"]


def _stale_run(prices):
    """Length (in minutes) the last price has been unchanged."""
    x = prices[-1]
    run = 0
    for v in reversed(prices):
        if v != x:
            break
        run += 1
    return run - 1  # k equal prices span k-1 minute gaps


def _bucket_mult(h, p):
    """Horizon-bucket width multiplier for horizon h (1-based)."""
    for h_max, mult in p["buckets"]:
        if h <= h_max:
            return mult
    return p["buckets"][-1][1]


def forecast_case(case, p=None):
    """Forecast one case: list of {"id": ..., "q": [[5 quantiles] x 240]}."""
    p = PARAMS if p is None else p
    horizon = case["horizon_minutes"]
    markets = case["markets"]
    n = len(markets)
    last = [m["prices"][-1] for m in markets]
    total = sum(last)  # S: sum of the checkpoint prices

    # Per-market vol, staleness and activity counts (computed once).
    sig = []
    changes = []
    for m in markets:
        prices = m["prices"]
        d = _diffs(prices)
        s = _sigma(prices, p)
        if _stale_run(prices) >= p["stale_minutes"]:
            s *= p["stale_mult"]
        changes.append(sum(1 for v in d if v != 0))
        sig.append(s)
    # Activity tier: top tertile by change count gets the widening.
    order = sorted(range(n), key=lambda i: changes[i])
    n_top = (n + 2) // 3  # ceil(n/3)
    active = set(order[n - n_top:])
    for i in active:
        sig[i] *= p["active_mult"]

    out = []
    for i, m in enumerate(markets):
        x = last[i]
        target = x / total if total > 0 else x
        rows = []
        for h in range(1, horizon + 1):
            glide = 1.0 - math.exp(-h / p["tau"])
            centre = x + glide * (target - x)
            mult = _bucket_mult(h, p) * sig[i] * math.sqrt(h)
            row = [price6(centre + mult * Z[j] + p["offsets"][j])
                   for j in range(5)]
            for j in range(1, 5):  # enforce non-decreasing quantiles
                if row[j] < row[j - 1]:
                    row[j] = row[j - 1]
            rows.append(row)
        out.append({"id": m["id"], "q": rows})
    return out


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
