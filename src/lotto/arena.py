"""Strategy arena: backtest pick methods against real draw history.

For each of the last N draws, each strategy generates a pick using only the
draws that came before it (a rolling window for hot/cold), then we count how
many numbers it matched. This is the honest demonstration that no method
beats any other over time.
"""
from __future__ import annotations
import hashlib
from collections import Counter

from .feeds import Draw, get_draws
from .games import GAMES, Game
from .rng import ChaChaRNG
from .stats import era_draws, frequency, gaps, pair_frequency

ARENA_STRATEGIES = ["pure", "hot", "cold", "birthday", "pairs", "phrase"]


def _weights_from_counts(game: Game, counts: dict[int, int], invert: bool) -> list[float]:
    vals = [counts.get(n, 0) for n in range(game.main.lo, game.main.hi + 1)]
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1
    out = []
    for v in vals:
        x = (v - lo) / span
        if invert:
            x = 1 - x
        out.append(0.15 + 2.0 * x)
    return out


def _pick(game: Game, strategy: str, window: list[Draw], rng: ChaChaRNG, t: float, phrase_w: list[float]) -> list[int]:
    k = game.main.count
    lo, hi = game.main.lo, game.main.hi
    if not game.main.distinct:
        return [rng.randint(lo, hi) for _ in range(k)]
    if strategy == "pure":
        return rng.sample_distinct(lo, hi, k)
    if strategy == "birthday":
        top = min(hi, 31)
        return rng.sample_distinct(lo, top, k)
    if strategy == "phrase":
        w = phrase_w
    elif strategy == "hot":
        w = _weights_from_counts(game, frequency(game, window), False)
    elif strategy == "cold":
        w = _weights_from_counts(game, gaps(game, window), False)
    elif strategy == "pairs":
        w = _weights_from_counts(game, frequency(game, window), False)
        for (a, b), _ in pair_frequency(window, 15):
            w[a - lo] *= 1.35
            w[b - lo] *= 1.35
    else:
        raise ValueError(strategy)
    flat = sum(w) / len(w)
    w = [(1 - t) * x + t * flat for x in w]
    idx = rng.weighted_sample_distinct(w, k)
    return sorted(lo + i for i in idx)


def run_arena(game_key: str, n_draws: int = 300, window: int = 200, entropy: float = 0.3, seed: bytes | None = None,
              strategies: list[str] | None = None, phrase: str = "entropy lab") -> dict:
    game = GAMES[game_key]
    if game.feed_id is None:
        return {"available": False, "reason": "no history for this game"}
    draws = era_draws(game, get_draws(game_key), current_era=True)
    if len(draws) < window + 10:
        window = max(20, len(draws) // 3)
    n_draws = min(n_draws, len(draws) - window)
    if n_draws <= 0:
        return {"available": False, "reason": "not enough history"}
    strategies = strategies or ARENA_STRATEGIES
    seed = seed or b"\x00" * 32
    h = hashlib.sha512(phrase.encode()).digest()
    prng = ChaChaRNG(h[:32])
    phrase_w = [0.15 + prng.unit() * 2.5 for _ in range(game.main.size)]

    results = {}
    for s in strategies:
        rng = ChaChaRNG(hashlib.sha256(seed + s.encode()).digest())
        matches = Counter()
        bonus_hits = 0
        total = 0
        for i in range(n_draws):
            target = draws[i]
            win = draws[i + 1: i + 1 + window]
            pick = _pick(game, s, win, rng, entropy, phrase_w)
            if game.main.distinct:
                m = len(set(pick) & set(target.main))
            else:
                m = sum(1 for a, b in zip(pick, target.main) if a == b)
            matches[m] += 1
            total += m
            if game.bonus and target.bonus is not None:
                bonus_hits += int(rng.randint(game.bonus.lo, game.bonus.hi) == target.bonus)
        results[s] = {
            "avg_match": round(total / n_draws, 3),
            "distribution": {str(k): v for k, v in sorted(matches.items())},
            "three_plus": sum(v for k, v in matches.items() if k >= 3),
            "bonus_hits": bonus_hits,
        }
    k, size = game.main.count, game.main.size
    expected = round(k * k / size, 3) if game.main.distinct else round(k / 10, 3)
    return {
        "available": True, "game": game_key, "draws_tested": n_draws, "window": window, "entropy": entropy,
        "expected_avg_match": expected, "results": results,
        "leaderboard": sorted(results, key=lambda s: -results[s]["avg_match"]),
    }
