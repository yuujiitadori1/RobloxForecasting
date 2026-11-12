# Roblox Up-and-Coming Forecaster v2

Momentum-based forecaster for the make.fun bounty
**roblox-up-and-coming-forecast-01** — Predict Roblox's Up-and-Coming top 10.

## Strategy

The Up-and-Coming chart is highly volatile: the median read changes 6 of
the top 10 places, and the #1 changed 13 times in 45 reads. A persistence
forecast (the house baseline) scores -43.5 on practice because the chart
moves away from it.

This forecaster uses **momentum**, not persistence:

1. **Velocity** — rank change per day over the last 5 reads. Positive means
   climbing. Capped at 20 ranks/day and weighted by number of reads (a game
   that just appeared gets less velocity credit).
2. **Acceleration** — change in velocity between the first and second half
   of the lookback window. A climb that is speeding up scores higher.
3. **Playing growth** — fractional change in concurrent players. Capped at
   100% to avoid small-base explosions.
4. **Recency** — newly-appeared games get a small boost (they are hot).
5. **Rank factor** — games below #30 are heavily penalised (unlikely to
   reach the top 10 in 72 hours); below #40 almost excluded.

For each place, the predicted rank is `current_rank - velocity * 1.5`
(1.5 days of expected movement). Probabilities are spread across the top
20 candidates per place using a softmax, capped at 0.5 per game per place,
with each place summing to 0.85 (leaving 0.15 unnamed for chart churn).

The top 10 blends current rank (persistence) with momentum bonus, so it
stays close to the current chart while promoting fast climbers.

## Usage

```bash
mkdir -p out
MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

Reads `/input/history.ndjson` and `/input/task.json`, writes
`/output/forecast.json` with `probabilities` and `top10`.

## Files

- `main.py` — the forecaster (Python 3.13, stdlib only)
- `README.md` — this file
- `LICENSE` — MIT

## License

MIT
