"""Wheeling systems: play a set of favorite numbers across several tickets.

full      every combination of your numbers (can be large)
abbrev    greedy covering design: guarantee that if `guarantee` of your
          numbers are drawn, at least one ticket holds all of them
key       one key number appears on every ticket, the rest are wheeled
"""
from __future__ import annotations
from itertools import combinations
from math import comb

from .games import GAMES
from .rng import ChaChaRNG

MAX_TICKETS = 500


def full_wheel(game_key: str, numbers: list[int]) -> list[list[int]]:
    g = GAMES[game_key]
    k = g.main.count
    numbers = sorted(set(numbers))
    if len(numbers) < k:
        raise ValueError(f"need at least {k} numbers")
    n = comb(len(numbers), k)
    if n > MAX_TICKETS:
        raise ValueError(f"full wheel of {len(numbers)} numbers is {n} tickets; max {MAX_TICKETS}")
    return [list(c) for c in combinations(numbers, k)]


def abbreviated_wheel(game_key: str, numbers: list[int], guarantee: int, seed: bytes | None = None) -> list[list[int]]:
    """Greedy set cover: every `guarantee`-subset of `numbers` is inside at least one ticket."""
    g = GAMES[game_key]
    k = g.main.count
    numbers = sorted(set(numbers))
    if len(numbers) < k:
        raise ValueError(f"need at least {k} numbers")
    if not (2 <= guarantee <= k):
        raise ValueError(f"guarantee must be between 2 and {k}")
    if comb(len(numbers), k) > 200_000:
        raise ValueError("too many numbers to wheel; use 12 or fewer")
    rng = ChaChaRNG(seed) if seed else None
    targets = {frozenset(c) for c in combinations(numbers, guarantee)}
    candidates = [frozenset(c) for c in combinations(numbers, k)]
    if rng:
        candidates = rng.shuffle(candidates)
    covered: set[frozenset] = set()
    tickets: list[list[int]] = []
    cover_of = {c: {frozenset(s) for s in combinations(sorted(c), guarantee)} for c in candidates}
    while covered != targets and len(tickets) < MAX_TICKETS:
        best = max(candidates, key=lambda c: len(cover_of[c] - covered))
        gain = cover_of[best] - covered
        if not gain:
            break
        covered |= gain
        tickets.append(sorted(best))
        candidates.remove(best)
    return tickets


def key_wheel(game_key: str, key_number: int, others: list[int], seed: bytes | None = None) -> list[list[int]]:
    g = GAMES[game_key]
    k = g.main.count
    others = sorted(set(others) - {key_number})
    if len(others) < k - 1:
        raise ValueError(f"need at least {k - 1} other numbers")
    combos = [sorted([key_number, *c]) for c in combinations(others, k - 1)]
    if len(combos) > MAX_TICKETS:
        raise ValueError(f"{len(combos)} tickets; max {MAX_TICKETS}")
    if seed:
        combos = ChaChaRNG(seed).shuffle(combos)
    return combos


def wheel_info(game_key: str, n_numbers: int) -> dict:
    g = GAMES[game_key]
    k = g.main.count
    return {
        "picks_per_ticket": k,
        "full_tickets": comb(n_numbers, k) if n_numbers >= k else 0,
        "abbrev_guarantees": list(range(2, k + 1)),
    }
