#!/usr/bin/env python3
"""
Roblox Up-and-Coming Forecaster v2
Momentum-based forecast for make.fun bounty roblox-up-and-coming-forecast-01.

Strategy: The Up-and-Coming chart is highly volatile (median 6 places change
per read). Persistence fails (baseline scores -43.5). This forecaster uses:
  1. Velocity: rank change per day over recent reads
  2. Acceleration: change in velocity (is the climb speeding up?)
  3. Playing growth: player count momentum
  4. Recency weighting: recent reads matter more than old ones

Probabilities are spread across the top 20 candidates per place, not just
the current top 10, because the chart churns fast.
"""

import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

INPUT_DIR = os.environ.get("MAKEFUN_INPUT_DIR", "/input")
OUTPUT_DIR = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")


def parse_time(s):
    """Parse ISO 8601 UTC timestamp."""
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def load_history(input_dir):
    """Load all reads from history.ndjson, oldest first."""
    path = os.path.join(input_dir, "history.ndjson")
    reads = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            data["_dt"] = parse_time(data["at"])
            reads.append(data)
    return reads


def load_task(input_dir):
    """Load task.json for places and output filename."""
    path = os.path.join(input_dir, "task.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def compute_momentum(reads, lookback=5):
    """
    Compute momentum score for each game based on recent reads.

    Returns dict: universe_id -> {
        'name': str,
        'last_rank': int,
        'velocity': float (ranks/day, positive = climbing),
        'acceleration': float (change in velocity),
        'playing_growth': float (fractional change in players),
        'recency': float (0-1, how recently first seen),
        'score': float (combined momentum score),
    }
    """
    # Build rank and playing history per game
    rank_hist = defaultdict(list)  # uid -> [(dt, rank)]
    play_hist = defaultdict(list)  # uid -> [(dt, playing)]
    name_map = {}

    for r in reads:
        for row in r["up_and_coming"]:
            uid = row["universe_id"]
            rank_hist[uid].append((r["_dt"], row["rank"]))
            play_hist[uid].append((r["_dt"], row.get("playing") or 0))
            if uid not in name_map:
                name_map[uid] = row.get("name", "?")

    last_dt = reads[-1]["_dt"]
    first_dt = reads[0]["_dt"]
    total_span = max((last_dt - first_dt).total_seconds() / 86400, 0.1)

    result = {}
    for uid, hist in rank_hist.items():
        # Use last N reads for velocity
        recent = hist[-lookback:]
        if len(recent) < 2:
            continue

        last_rank = recent[-1][1]

        # Velocity: rank change per day (positive = climbing up the chart)
        dt_days = (recent[-1][0] - recent[0][0]).total_seconds() / 86400
        dt_days = max(dt_days, 0.1)
        velocity = (recent[0][1] - recent[-1][1]) / dt_days

        # Acceleration: compare velocity in first half vs second half
        if len(recent) >= 4:
            mid = len(recent) // 2
            dt1 = (recent[mid][0] - recent[0][0]).total_seconds() / 86400
            dt2 = (recent[-1][0] - recent[mid][0]).total_seconds() / 86400
            dt1 = max(dt1, 0.1)
            dt2 = max(dt2, 0.1)
            v1 = (recent[0][1] - recent[mid][1]) / dt1
            v2 = (recent[mid][1] - recent[-1][1]) / dt2
            acceleration = v2 - v1
        else:
            acceleration = 0.0

        # Playing growth over recent reads
        plays = play_hist[uid]
        recent_plays = plays[-lookback:]
        if len(recent_plays) >= 2 and recent_plays[0][1] > 0:
            playing_growth = (recent_plays[-1][1] - recent_plays[0][1]) / recent_plays[0][1]
        else:
            playing_growth = 0.0

        # Recency: how recently the game first appeared (new games get boost)
        first_seen = hist[0][0]
        age_days = (last_dt - first_seen).total_seconds() / 86400
        recency = max(0.0, 1.0 - age_days / total_span)

        # Combined momentum score
        # Cap velocity: a game that just appeared looks fast but
        # can't sustain it. Require at least 3 reads for full velocity credit.
        n_reads = len(hist)
        vel_weight = min(1.0, n_reads / 5.0)
        capped_velocity = velocity * vel_weight
        # Cap velocity at 20 ranks/day (beyond that is noise)
        capped_velocity = max(-20, min(20, capped_velocity))

        # Playing growth: cap at 100% to avoid small-base explosion
        capped_growth = max(-0.5, min(1.0, playing_growth))

        # Rank penalty: games below #30 are very unlikely to reach top 10
        # in 72 hours. Strong penalty below #20, hard cutoff below #40.
        if last_rank > 40:
            rank_factor = 0.1
        elif last_rank > 30:
            rank_factor = 0.3
        elif last_rank > 20:
            rank_factor = 0.6
        else:
            rank_factor = 1.0

        score = (
            capped_velocity * 1.0
            + acceleration * 0.3
            + capped_growth * 8.0
            + recency * 1.0
            # Rank bonus: being high already matters (persistence component)
            + max(0, (30 - last_rank)) * 0.5
        ) * rank_factor

        result[uid] = {
            "name": name_map[uid],
            "last_rank": last_rank,
            "velocity": velocity,
            "acceleration": acceleration,
            "playing_growth": playing_growth,
            "recency": recency,
            "score": score,
        }

    return result


def main():
    task = load_task(INPUT_DIR)
    reads = load_history(INPUT_DIR)
    places = task["places"]
    output_file = task["output"]

    # Compute momentum for all games
    momentum = compute_momentum(reads, lookback=5)

    # Sort by momentum score (descending) for candidate ranking
    ranked = sorted(momentum.items(), key=lambda x: x[1]["score"], reverse=True)

    # Also get the last chart order for persistence baseline
    last_chart = sorted(
        reads[-1]["up_and_coming"], key=lambda r: r["rank"]
    )
    last_order = [r["universe_id"] for r in last_chart]

    print(f"Loaded {len(reads)} reads, {places} places", file=sys.stderr)
    print(f"Last read: {reads[-1]['at']}", file=sys.stderr)
    print(f"Top 5 by momentum:", file=sys.stderr)
    for uid, m in ranked[:5]:
        print(
            f"  {m['name'][:40]}: score={m['score']:.1f} "
            f"rank=#{m['last_rank']} vel={m['velocity']:+.1f}/d "
            f"play={m['playing_growth']:+.0%}",
            file=sys.stderr,
        )

    # Generate probabilities per place
    probabilities = []
    top10 = []

    # For each place, distribute probability across candidates
    # The predicted rank for a game is a blend of its current rank
    # and its momentum-adjusted rank
    for place in range(1, places + 1):
        # Score each candidate for this specific place
        # A game is likely at place k if:
        #   - its momentum-adjusted rank is near k
        #   - its current rank is near k (persistence)
        place_scores = []
        for uid, m in momentum.items():
            # Predicted rank: current rank minus expected climb
            # Velocity is ranks/day; window is 72 hours = 3 days
            # But momentum decays: use 1.5 days of expected movement
            predicted_rank = m["last_rank"] - m["velocity"] * 1.5
            predicted_rank = max(1, predicted_rank)

            # Distance from this place (closer = higher score)
            dist = abs(predicted_rank - place)
            # Gaussian-like falloff
            place_score = m["score"] * 0.1 + max(0, 20 - dist * 2)
            # Bonus if current rank is exactly this place
            if m["last_rank"] == place:
                place_score += 15
            # Bonus if predicted rank is exactly this place
            if round(predicted_rank) == place:
                place_score += 10

            place_scores.append((uid, place_score))

        # Sort by place score, take top 20
        place_scores.sort(key=lambda x: x[1], reverse=True)
        top_candidates = place_scores[:20]

        # Convert scores to probabilities using softmax-like normalization
        # Use temperature to spread probabilities (not too peaked)
        import math
        total = sum(math.exp(min(s / 10.0, 5.0)) for _, s in top_candidates)
        place_total = 0.0
        for uid, s in top_candidates:
            p = math.exp(min(s / 10.0, 5.0)) / total
            # Cap at 0.5 per game per place (don't overcommit)
            p = min(p, 0.5)
            # Floor at 0.01 (avoid wasting probability on tiny chances)
            if p < 0.01:
                continue
            probabilities.append(
                {"universe_id": uid, "place": place, "p": round(p, 4)}
            )
            place_total += p

        # Normalize so place sums to <= 0.85 (leave 0.15 unnamed for churn)
        # Scale down if over 0.85
        if place_total > 0.85:
            scale = 0.85 / place_total
            for prob in probabilities:
                if prob["place"] == place:
                    prob["p"] = round(prob["p"] * scale, 4)

    # Top 10: blend of current rank and momentum
    # Score each game for top10: current rank matters most (persistence),
    # momentum is a tiebreaker/boost for climbers
    top10_scores = []
    for uid, m in momentum.items():
        # Base score from current rank (lower rank = higher score)
        rank_score = max(0, 30 - m["last_rank"]) * 2.0
        # Momentum bonus (capped so it can't overwhelm rank)
        mom_bonus = min(m["score"], 25) * 0.5
        total = rank_score + mom_bonus
        top10_scores.append((uid, total))

    top10_scores.sort(key=lambda x: x[1], reverse=True)
    top10 = [uid for uid, _ in top10_scores[:places]]

    # Write output
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_path = os.path.join(OUTPUT_DIR, output_file)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(
            {"probabilities": probabilities, "top10": top10[:places]},
            f,
        )
        f.write("\n")

    print(f"Wrote {output_path}: {len(probabilities)} rows, top10={top10[:places]}", file=sys.stderr)


if __name__ == "__main__":
    main()
