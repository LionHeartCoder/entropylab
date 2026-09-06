"""Historical statistics: hot/cold numbers, overdue gaps, pairs, sums, and era filtering.

Every draw is independent, so none of this predicts anything. It is here
for the research panel and the for-fun pick modes.
"""
from __future__ import annotations
from collections import Counter
from itertools import combinations

from .feeds import Draw, get_draws
from .games import GAMES, Game


def era_draws(game: Game, draws: list[Draw], current_era: bool = True) -> list[Draw]:
    """Keep only draws that fit the current rules (range and count)."""
    out = []
    for d in draws:
        if current_era and game.era_start and d.date < game.era_start:
            continue
        if not d.main or len(d.main) != game.main.count:
            if not game.main.user_sets_count:
                continue
        if any(n < game.main.lo or n > game.main.hi for n in d.main):
            continue
        if game.bonus and d.bonus is not None and not (game.bonus.lo <= d.bonus <= game.bonus.hi):
            continue
        out.append(d)
    return out


def frequency(game: Game, draws: list[Draw], pool: str = "main") -> dict[int, int]:
    p = game.main if pool == "main" else game.bonus
    counts = Counter({n: 0 for n in range(p.lo, p.hi + 1)})
    for d in draws:
        if pool == "main":
            counts.update(d.main)
        elif d.bonus is not None:
            counts[d.bonus] += 1
    return dict(counts)


def gaps(game: Game, draws: list[Draw], pool: str = "main") -> dict[int, int]:
    """Draws since each number last appeared (draws are newest first)."""
    p = game.main if pool == "main" else game.bonus
    last: dict[int, int] = {}
    for i, d in enumerate(draws):
        seen = d.main if pool == "main" else ([d.bonus] if d.bonus is not None else [])
        for n in seen:
            last.setdefault(n, i)
    total = len(draws)
    return {n: last.get(n, total) for n in range(p.lo, p.hi + 1)}


def pair_frequency(draws: list[Draw], top: int = 30) -> list[tuple[tuple[int, int], int]]:
    c: Counter = Counter()
    for d in draws:
        for a, b in combinations(sorted(set(d.main)), 2):
            c[(a, b)] += 1
    return c.most_common(top)


def triplet_frequency(draws: list[Draw], top: int = 20) -> list[tuple[tuple[int, int, int], int]]:
    c: Counter = Counter()
    for d in draws:
        for t in combinations(sorted(set(d.main)), 3):
            c[t] += 1
    return c.most_common(top)


def sum_distribution(draws: list[Draw]) -> dict:
    sums = sorted(sum(d.main) for d in draws if d.main)
    if not sums:
        return {"min": 0, "max": 0, "p10": 0, "p90": 0, "median": 0}
    q = lambda f: sums[min(len(sums) - 1, int(f * len(sums)))]  # noqa: E731
    return {"min": sums[0], "max": sums[-1], "p10": q(0.10), "p90": q(0.90), "median": q(0.5)}


def odd_even_split(draws: list[Draw]) -> dict[str, int]:
    c: Counter = Counter()
    for d in draws:
        odd = sum(1 for n in d.main if n % 2)
        c[f"{odd} odd / {len(d.main) - odd} even"] += 1
    return dict(c.most_common())


def digit_frequency(draws: list[Draw], positions: int) -> list[dict[int, int]]:
    """For Pick 3/4/5: per-position digit counts."""
    out = [Counter({d: 0 for d in range(10)}) for _ in range(positions)]
    for d in draws:
        if len(d.main) != positions:
            continue
        for i, n in enumerate(d.main):
            out[i][n] += 1
    return [dict(c) for c in out]


def already_hit(game: Game, draws: list[Draw], main: list[int], bonus: int | None = None) -> Draw | None:
    key = tuple(sorted(main)) if game.main.distinct else tuple(main)
    for d in draws:
        dk = tuple(sorted(d.main)) if game.main.distinct else tuple(d.main)
        if dk == key and (bonus is None or d.bonus == bonus):
            return d
    return None


def game_stats(game_key: str, current_era: bool = True) -> dict:
    game = GAMES[game_key]
    if game.feed_id is None:
        return {"game": game_key, "available": False, "reason": "no results feed for this game"}
    all_draws = get_draws(game_key)
    draws = era_draws(game, all_draws, current_era=current_era)
    freq = frequency(game, draws, "main")
    gap = gaps(game, draws, "main")
    out = {
        "game": game_key,
        "available": True,
        "current_era": current_era,
        "era_start": game.era_start,
        "draws_total": len(all_draws),
        "draws_used": len(draws),
        "first_date": draws[-1].date if draws else None,
        "last_date": draws[0].date if draws else None,
        "main": {
            "frequency": freq,
            "gaps": gap,
            "hot": [n for n, _ in sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))[:10]],
            "cold": [n for n, _ in sorted(gap.items(), key=lambda kv: (-kv[1], kv[0]))[:10]],
        },
        "latest": draws[0].as_dict() if draws else None,
    }
    if game.bonus:
        bf = frequency(game, draws, "bonus")
        bg = gaps(game, draws, "bonus")
        out["bonus"] = {
            "frequency": bf,
            "gaps": bg,
            "hot": [n for n, _ in sorted(bf.items(), key=lambda kv: (-kv[1], kv[0]))[:5]],
            "cold": [n for n, _ in sorted(bg.items(), key=lambda kv: (-kv[1], kv[0]))[:5]],
        }
    if game.main.distinct and game.main.count > 1:
        out["pairs"] = [{"pair": list(p), "count": c} for p, c in pair_frequency(draws)]
        out["triplets"] = [{"triplet": list(t), "count": c} for t, c in triplet_frequency(draws)]
        out["sums"] = sum_distribution(draws)
        out["odd_even"] = odd_even_split(draws)
    if not game.main.distinct:
        out["digits"] = digit_frequency(draws, game.main.count)
    return out
