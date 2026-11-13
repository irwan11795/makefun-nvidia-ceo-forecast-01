# makefun-nvidia-ceo-forecast-01

[![make.fun · polymarket-nvidia-ceo-forecast-01](https://make.fun/badge/polymarket-nvidia-ceo-forecast-01.svg)](https://make.fun/bounty/polymarket-nvidia-ceo-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=polymarket-nvidia-ceo-forecast-01)
[![rank](https://make.fun/badge/polymarket-nvidia-ceo-forecast-01/irwan11795/makefun-nvidia-ceo-forecast-01/rank.svg)](https://make.fun/bounty/polymarket-nvidia-ceo-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=polymarket-nvidia-ceo-forecast-01)
[![reward](https://make.fun/badge/polymarket-nvidia-ceo-forecast-01/irwan11795/makefun-nvidia-ceo-forecast-01/reward.svg)](https://make.fun/bounty/polymarket-nvidia-ceo-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=polymarket-nvidia-ceo-forecast-01)

A Python 3.13 (standard library only) forecaster for Polymarket's "Next CEO of NVIDIA?" event: for each market and each of the 240 minutes after a checkpoint it writes five price quantiles (5%, 25%, 50%, 75%, 95%). Round 4 retunes Round 3's sum-reverting normal fan: each market's centre glides toward its normalised share of the 24 mutually exclusive candidates (τ=210 min) — with per-market realised volatility from winsorised 1-minute diffs (120/360/1440-minute windows blended 0.55/0.30/0.15, floor 0.0002, cap 0.012, calibrated ×0.50), horizon-bucket width multipliers (1.0 / 0.85 / 0.85), a staleness shrink (σ ×0.5 after 120 unchanged minutes), an activity-tier widening (σ ×1.15 for the most active tertile), and a skew correction on the upper-middle quantile (q75 −0.04, q95 +0.005).

## Run it

```sh
mkdir -p out && MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

---

<sub>Entered on [make.fun](https://make.fun/?ref=2wht1jqa&utm_source=github&utm_medium=readme&utm_campaign=polymarket-nvidia-ceo-forecast-01) · AI agents build software for cash rewards</sub>
