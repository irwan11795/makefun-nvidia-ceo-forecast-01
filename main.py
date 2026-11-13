# Polymarket "Next CEO of NVIDIA?" forecaster v4 (make.fun polymarket-nvidia-ceo-forecast-01).
#
# v4 starts from our submitted v3 (sum-reverting normal fan, RMS vol
# calibrated x0.47 -- see GRIND-V3.md) and adds four new knobs, all
# defaulting to v3 behaviour, to test structural ideas v3 never tried:
#
# (a) vol_mode: "rms" (v3), "meanabs" (the reference's estimator,
#     normal-consistent sqrt(pi/2)*E|d|), or "blend" -- a mix of the two
#     calibrated sigmas, weight vol_blend_w on meanabs. RMS wins on quiet
#     practice cases; meanabs is jump-robust; a blend may dominate both.
# (b) stale_blocks_active: if True, a stale market does NOT get the
#     activity-tier widening (staleness overrides activity).
# (c) active_window: if set (minutes), the activity tier counts price
#     changes only over the last N minutes instead of the whole case.
# (d) tau_gap_k: if > 0, the sum-reversion time constant becomes
#     tau / (1 + k*|target - x|) -- markets far from their normalised
#     share glide faster.
#
# WHAT SHIPPED (this file): tau 210, sigma_scale 0.50, window weights
# 0.55/0.30/0.15 -- centre of a flat plateau (neighbours tau 200-220,
# scale 0.49-0.51, weights .55/.3/.15-.6/.3/.1 all similar), NOT the
# argmin. Verified practice loss (our grade.py): mean 0.248323
# (p00 0.382963, p01 0.297720, p02 0.326009, p03 0.246519, p04 0.186512,
# p05 0.104664; wins 4/6 vs v3). Out-of-sample: 27 pseudo-cases 0.914960
# (v3: 0.933348), Nov-12 subset (15) 0.380100 (v3: 0.381742), Nov-11
# subset (12, volatile) 3.254973 (v3: 3.346622). LOO: beats v3 on 5/6
# subsets; the p03-dropped subset is +0.000578 worse (the practice gain
# is concentrated in p03 -- see GRIND-V4.md for the honest caveats).
# The v4 knobs below were all tested and REJECTED (blend, stale-block,
# active window, gap-scaled tau, glide skew); they stay in the file at
# their inert defaults so the experiments are reproducible.
#
# Base design (v3 = reference v6 + 2 measured changes):
# 1. MEDIAN = persistence + sum-reversion: centre_i(h) = x_i +
#    (1 - exp(-h/TAU)) * (x_i/S - x_i), TAU = 210, S = sum of the last
#    prices of all markets. The glide applies to the WHOLE fan.
# 2. SIGMA = realised vol per market, from 1-minute diffs winsorised at
#    +-0.05, blended over trailing windows 120/360/1440 min (0.55/0.30/0.15),
#    floored at 0.0002, capped at 0.012, scaled by 0.50. Fan half-width:
#    width_j(h) = z_j * sigma * sqrt(h).
# 3. HORIZON BUCKETS multiply the fan width: 1.0 (h 1-30), 0.85 (31-120),
#    0.85 (121-240).
# 4. STALENESS: last price unchanged >=120 min -> sigma x 0.5.
# 5. ACTIVITY TIER: top tertile by change count -> sigma x 1.15.
# 6. QUANTILE OFFSETS (additive): (0, 0, 0, -0.04, +0.005).
#
# v3 verified practice loss (our grade.py): mean 0.248893
# (p00 0.378211, p01 0.298991, p02 0.323896, p03 0.252330, p04 0.187394,
# p05 0.105682; med_err 0.748344, cov90 0.9430). Out-of-sample: 27
# pseudo-cases 0.933348, Nov-12 subset (15) 0.381742, LOO all positive.
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

# --- v4 SHIPPED parameters (centre of the plateau, NOT the argmin) ---
# tau 210 (v3: 180), sigma_scale 0.50 (v3: 0.47), window weights
# 0.55/0.30/0.15 (v3: 0.4/0.4/0.2). The three changes are complementary:
# slower glide + wider fan insure the volatile regime, the recent-weighted
# vol sharpens the quiet regime; each alone fails (tau/scale alone:
# practice +0.0008, 0/6 wins; weights alone: pseudo +0.0030), together
# they improve practice AND all out-of-sample sets (see GRIND-V4.md).
PARAMS = {
    "tau": 210.0,            # sum-reversion glide time constant (minutes)
    "win_weights": ((120, 0.55), (360, 0.3), (1440, 0.15)),  # vol windows
    "winsor": 0.05,          # per-diff winsor cap
    "sigma_floor": 0.0002,
    "sigma_cap": 0.012,
    "buckets": ((30, 1.0), (120, 0.85), (240, 0.85)),  # (h_max, mult)
    "stale_minutes": 120,    # unchanged-price run that counts as stale
    "stale_mult": 0.5,
    "active_mult": 1.15,     # top-tertile activity widening
    "offsets": (0.0, 0.0, 0.0, -0.04, 0.005),
    "sigma_scale": 0.50,     # global calibration on RMS sigma
    # --- v4 knobs (defaults reproduce v3 exactly; all tested, see GRIND-V4.md) ---
    "vol_mode": "rms",       # "rms" | "meanabs" | "blend"
    "meanabs_scale": 1.0,    # calibration on the meanabs estimator
    "vol_blend_w": 0.5,      # weight on meanabs when vol_mode == "blend"
    "stale_blocks_active": False,  # stale markets skip active widening
    "active_window": None,   # minutes of recent history for activity count
    "tau_gap_k": 0.0,        # >0: tau_eff = tau / (1 + k*|target - x|)
    "glide_skew": 0.0,       # >0: fan widens in the glide direction, narrows opposite
}


def price6(x):
    """Clamp to [0, 1] and round to 6 decimals (0, never -0)."""
    return round(min(1.0, max(0.0, x)) * 1e6) / 1e6 + 0.0


def _diffs(prices):
    """1-minute diffs of a price series."""
    return [prices[i + 1] - prices[i] for i in range(len(prices) - 1)]


def _sigma_rms(win, p):
    """RMS of winsorised diffs over trailing windows, blended."""
    sig = 0.0
    for minutes, weight in p["win_weights"]:
        seg = win[-minutes:] if len(win) > minutes else win
        n = len(seg)
        var = sum(d * d for d in seg) / n
        sig += weight * math.sqrt(var)
    return sig


def _sigma_meanabs(win, p):
    """Normal-consistent mean-absolute-diff estimator: sqrt(pi/2)*E|d|,
    blended over the same trailing windows."""
    sig = 0.0
    for minutes, weight in p["win_weights"]:
        seg = win[-minutes:] if len(win) > minutes else win
        n = len(seg)
        sig += weight * math.sqrt(math.pi / 2.0) * sum(abs(d) for d in seg) / n
    return sig


def _sigma(prices, p):
    """Blended realised vol, floored/capped BEFORE scaling per vol_mode
    (v3 applies floor/cap first, then the scale -- the effective floor is
    floor*scale)."""
    diffs = _diffs(prices)
    w = p["winsor"]
    win = [max(-w, min(w, d)) for d in diffs]
    if not win:
        return p["sigma_floor"]
    mode = p.get("vol_mode", "rms")
    floor = p["sigma_floor"]
    cap = p["sigma_cap"]
    if mode == "meanabs":
        raw = _sigma_meanabs(win, p)
        return min(max(raw, floor), cap) * p.get("meanabs_scale", 1.0)
    if mode == "blend":
        bw = p.get("vol_blend_w", 0.5)
        rms = min(max(_sigma_rms(win, p), floor), cap) * p["sigma_scale"]
        mab = min(max(_sigma_meanabs(win, p), floor), cap) * p.get("meanabs_scale", 1.0)
        return (1.0 - bw) * rms + bw * mab
    raw = _sigma_rms(win, p)
    return min(max(raw, floor), cap) * p["sigma_scale"]


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
    stale = []
    for m in markets:
        prices = m["prices"]
        d = _diffs(prices)
        s = _sigma(prices, p)
        is_stale = _stale_run(prices) >= p["stale_minutes"]
        if is_stale:
            s *= p["stale_mult"]
        stale.append(is_stale)
        aw = p.get("active_window")
        if aw is not None:
            d = d[-aw:] if len(d) > aw else d
        changes.append(sum(1 for v in d if v != 0))
        sig.append(s)
    # Activity tier: top tertile by change count gets the widening.
    order = sorted(range(n), key=lambda i: changes[i])
    n_top = (n + 2) // 3  # ceil(n/3)
    active = set(order[n - n_top:])
    for i in active:
        if p.get("stale_blocks_active") and stale[i]:
            continue
        sig[i] *= p["active_mult"]

    out = []
    for i, m in enumerate(markets):
        x = last[i]
        target = x / total if total > 0 else x
        gap = abs(target - x)
        tau_eff = p["tau"]
        if p.get("tau_gap_k", 0.0):
            tau_eff = p["tau"] / (1.0 + p["tau_gap_k"] * gap)
        rows = []
        sk = p.get("glide_skew", 0.0)
        direction = 1.0 if target > x else (-1.0 if target < x else 0.0)
        for h in range(1, horizon + 1):
            glide = 1.0 - math.exp(-h / tau_eff)
            centre = x + glide * (target - x)
            mult = _bucket_mult(h, p) * sig[i] * math.sqrt(h)
            row = []
            for j in range(5):
                zj = Z[j]
                if sk and zj != 0.0:
                    zj = zj * (1.0 + sk * direction * (1.0 if zj > 0 else -1.0))
                row.append(price6(centre + mult * zj + p["offsets"][j]))
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
