"""Pick generation: base strategies, the entropy-influence slider, shape filters, batches.

A pick request is:
    game        which game
    count       for Keno / Cash Pop, how many numbers to play
    strategy    pure | hot | cold | lucky | phrase | pairs
    entropy     0..1  how much the entropy pool pulls away from the base (slider)
    mode        blend | drift   how the slider is applied
    lucky       user's numbers (main) for lucky strategy; locked ones always included
    locked      subset of lucky that must appear
    exclude     numbers never allowed
    filters     set of: anti_split, anti_pattern, balanced, never_hit
    phrase      text for the phrase strategy
"""
from __future__ import annotations
import hashlib
from dataclasses import dataclass, field

from .games import GAMES, Game, Pool
from .rng import ChaChaRNG

STRATEGIES = ("pure", "hot", "cold", "lucky", "phrase", "pairs")
FILTERS = ("anti_split", "anti_pattern", "balanced", "never_hit")
MODES = ("blend", "drift")


@dataclass
class PickRequest:
    game: str
    count: int | None = None
    strategy: str = "pure"
    entropy: float = 1.0
    mode: str = "blend"
    lucky: list[int] = field(default_factory=list)
    locked: list[int] = field(default_factory=list)
    lucky_bonus: int | None = None
    exclude: list[int] = field(default_factory=list)
    filters: list[str] = field(default_factory=list)
    phrase: str = ""
    current_era: bool = True

    def validate(self) -> Game:
        game = GAMES[self.game]
        if self.strategy not in STRATEGIES:
            raise ValueError(f"unknown strategy {self.strategy}")
        if self.mode not in MODES:
            raise ValueError(f"unknown mode {self.mode}")
        bad = [f for f in self.filters if f not in FILTERS]
        if bad:
            raise ValueError(f"unknown filter(s) {bad}")
        self.entropy = min(1.0, max(0.0, float(self.entropy)))
        if self.strategy == "pure":
            self.entropy = 1.0
        p = game.main
        if p.user_sets_count:
            if self.count is None:
                self.count = p.count
            if not (p.min_count <= self.count <= p.max_count):
                raise ValueError(f"{game.name}: pick between {p.min_count} and {p.max_count} numbers")
        else:
            self.count = p.count
        for n in self.lucky + self.locked + self.exclude:
            if not (p.lo <= n <= p.hi):
                raise ValueError(f"number {n} outside {p.lo}-{p.hi}")
        if len(self.locked) > self.count:
            raise ValueError("more locked numbers than the game allows")
        if set(self.locked) & set(self.exclude):
            raise ValueError("a number is both locked and excluded")
        return game


@dataclass
class Pick:
    game: str
    main: list[int]
    bonus: int | None
    strategy: str
    entropy: float
    mode: str
    filters: list[str]
    attempts: int
    base_main: list[int] | None = None
    base_bonus: int | None = None
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "game": self.game, "main": self.main, "bonus": self.bonus, "strategy": self.strategy,
            "entropy": self.entropy, "mode": self.mode, "filters": self.filters, "attempts": self.attempts,
            "base_main": self.base_main, "base_bonus": self.base_bonus, "notes": self.notes,
        }

    def display(self, game: Game | None = None) -> str:
        g = game or GAMES[self.game]
        if not g.main.distinct:
            s = "-".join(str(n) for n in self.main)
        else:
            s = " ".join(f"{n:02d}" for n in self.main)
        if self.bonus is not None and g.bonus:
            s += f"  {g.bonus.name} {self.bonus:02d}"
        return s


# ---------------------------------------------------------------- base weights

def _uniform(pool: Pool) -> dict[int, float]:
    return {n: 1.0 for n in range(pool.lo, pool.hi + 1)}


def _from_counts(pool: Pool, counts: dict[int, int], invert: bool = False) -> dict[int, float]:
    vals = [counts.get(n, 0) for n in range(pool.lo, pool.hi + 1)]
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1
    out = {}
    for n in range(pool.lo, pool.hi + 1):
        x = (counts.get(n, 0) - lo) / span  # 0..1
        if invert:
            x = 1 - x
        out[n] = 0.15 + 2.0 * x  # keep every number possible, but strongly tilted
    return out


def base_weights(req: PickRequest, game: Game, stats: dict | None) -> tuple[dict[int, float], dict[int, float] | None, list[str]]:
    """Return (main weights, bonus weights or None, notes)."""
    notes: list[str] = []
    main = _uniform(game.main)
    bonus = _uniform(game.bonus) if game.bonus else None

    if req.strategy in ("hot", "cold", "pairs"):
        if not stats or not stats.get("available"):
            notes.append("no history for this game; using flat weights")
        else:
            key = "frequency" if req.strategy in ("hot", "pairs") else "gaps"
            main = _from_counts(game.main, {int(k): v for k, v in stats["main"][key].items()})
            if bonus is not None and "bonus" in stats:
                bonus = _from_counts(game.bonus, {int(k): v for k, v in stats["bonus"][key].items()})
            if req.strategy == "pairs" and stats.get("pairs"):
                # boost numbers that appear in the most-drawn pairs
                for item in stats["pairs"][:15]:
                    for n in item["pair"]:
                        main[n] = main.get(n, 1.0) * 1.35
                notes.append("boosted numbers from the 15 most-drawn pairs")
    elif req.strategy == "lucky":
        if not req.lucky:
            notes.append("no lucky numbers given; using flat weights")
        else:
            main = {n: (6.0 if n in req.lucky else 0.25) for n in main}
        if bonus is not None and req.lucky_bonus is not None:
            bonus = {n: (6.0 if n == req.lucky_bonus else 0.25) for n in bonus}
    elif req.strategy == "phrase":
        if not req.phrase.strip():
            notes.append("phrase empty; using flat weights")
        else:
            h = hashlib.sha512(req.phrase.strip().encode()).digest()
            prng = ChaChaRNG(h[:32])
            main = {n: 0.15 + prng.unit() * 2.5 for n in main}
            if bonus is not None:
                bonus = {n: 0.15 + prng.unit() * 2.5 for n in bonus}
            notes.append("phrase gives a repeatable weight map")

    for n in req.exclude:
        main[n] = 0.0
    return main, bonus, notes


def positional_weights(req: PickRequest, game: Game, stats: dict | None) -> list[dict[int, float]] | None:
    """For digit games with hot/cold: one weight map per position."""
    if game.main.distinct or req.strategy not in ("hot", "cold") or not stats or not stats.get("digits"):
        return None
    out = []
    for pos_counts in stats["digits"]:
        counts = {int(k): v for k, v in pos_counts.items()}
        if req.strategy == "cold":
            hi = max(counts.values())
            counts = {k: hi - v for k, v in counts.items()}
        w = _from_counts(game.main, counts)
        for n in req.exclude:
            w[n] = 0.0
        out.append(w)
    return out


def blend(weights: dict[int, float], t: float) -> dict[int, float]:
    """t=0 keeps the base weights, t=1 is flat. Zero-weight (excluded) numbers stay zero."""
    total = sum(weights.values())
    n_alive = sum(1 for w in weights.values() if w > 0) or 1
    flat = total / n_alive
    return {k: (0.0 if w <= 0 else (1 - t) * w + t * flat) for k, w in weights.items()}


# ---------------------------------------------------------------- drawing

def _draw_pool(rng: ChaChaRNG, pool: Pool, weights: dict[int, float], k: int, locked: list[int], distinct: bool, t: float) -> list[int]:
    nums = list(range(pool.lo, pool.hi + 1))
    w = [weights.get(n, 0.0) for n in nums]
    out = list(locked)
    if distinct:
        for n in out:
            w[n - pool.lo] = 0.0
        if t <= 0.0:
            # deterministic: top weights, ties broken by entropy
            order = sorted((n for n in nums if w[n - pool.lo] > 0), key=lambda n: (-w[n - pool.lo], rng.unit()))
            out += order[: k - len(out)]
        else:
            idx = rng.weighted_sample_distinct(w, k - len(out))
            out += [nums[i] for i in idx]
        return sorted(out)
    # digits, repeats allowed
    while len(out) < k:
        if t <= 0.0:
            best = max((n for n in nums), key=lambda n: (w[n - pool.lo], rng.unit()))
            out.append(best)
        else:
            out.append(nums[rng.weighted_choice(w)])
    return out


def _drift(rng: ChaChaRNG, pool: Pool, base: list[int], t: float, distinct: bool, exclude: set[int]) -> list[int]:
    """Each base number rolls a random distance of up to t*range, wrapping around."""
    size = pool.size
    max_step = int(round(t * (size - 1)))
    out: list[int] = []
    for b in base:
        for _ in range(200):
            step = rng.randint(-max_step, max_step) if max_step > 0 else 0
            n = pool.lo + ((b - pool.lo + step) % size)
            if n in exclude or (distinct and n in out):
                if max_step == 0:
                    max_step = 1
                continue
            out.append(n)
            break
        else:
            raise RuntimeError("drift could not place a number")
    return sorted(out) if distinct else out


# ---------------------------------------------------------------- filters

def _has_pattern(nums: list[int]) -> str | None:
    s = sorted(nums)
    if len(s) < 3:
        return None
    diffs = [b - a for a, b in zip(s, s[1:])]
    if all(d == 1 for d in diffs):
        return "all consecutive"
    if len(set(diffs)) == 1:
        return f"arithmetic sequence (step {diffs[0]})"
    run = 1
    for d in diffs:
        run = run + 1 if d == 1 else 1
        if run >= 4:
            return "four in a row"
    if all(n % 10 == s[0] % 10 for n in s):
        return "same last digit"
    if all(n % 5 == 0 for n in s) or all(n % 7 == 0 for n in s):
        return "multiples pattern"
    return None


def check_filters(game: Game, main: list[int], bonus: int | None, filters: list[str], stats: dict | None) -> str | None:
    """Return a rejection reason, or None if the pick passes."""
    if "anti_split" in filters and game.main.distinct and game.main.hi > 31:
        if all(n <= 31 for n in main):
            return "all numbers are birthday numbers (1-31)"
    if "anti_pattern" in filters and game.main.distinct:
        why = _has_pattern(main)
        if why:
            return why
    if "balanced" in filters and game.main.distinct and len(main) >= 4:
        odd = sum(1 for n in main if n % 2)
        if odd == 0 or odd == len(main):
            return "all odd or all even"
        mid = (game.main.lo + game.main.hi) / 2
        high = sum(1 for n in main if n > mid)
        if high == 0 or high == len(main):
            return "all high or all low"
        if stats and stats.get("sums"):
            s = sum(main)
            if not (stats["sums"]["p10"] <= s <= stats["sums"]["p90"]):
                return f"sum {s} outside the usual range {stats['sums']['p10']}-{stats['sums']['p90']}"
    if "never_hit" in filters and stats and stats.get("available"):
        from .feeds import get_draws
        from .stats import already_hit, era_draws
        d = already_hit(game, era_draws(game, get_draws(game.key), False), main, bonus)
        if d:
            return f"this exact combination already won on {d.date}"
    return None


# ---------------------------------------------------------------- entry point

def generate(req: PickRequest, seed: bytes, stats: dict | None = None, max_attempts: int = 500) -> Pick:
    game = req.validate()
    if req.strategy in ("hot", "cold", "pairs") or "never_hit" in req.filters or "balanced" in req.filters:
        if stats is None and game.feed_id is not None:
            from .stats import game_stats
            stats = game_stats(game.key, current_era=req.current_era)
    rng = ChaChaRNG(seed)
    main_w, bonus_w, notes = base_weights(req, game, stats)
    pos_w = positional_weights(req, game, stats)
    t = req.entropy
    exclude = set(req.exclude)

    # base pick (what you'd get with the slider at 0)
    base_rng = ChaChaRNG(hashlib.sha256(b"base" + seed).digest())
    if pos_w:
        base_main = [_draw_pool(base_rng, game.main, w, 1, [], False, 0.0)[0] for w in pos_w]
    else:
        base_main = _draw_pool(base_rng, game.main, main_w, req.count, req.locked, game.main.distinct, 0.0)
    base_bonus = None
    if game.bonus:
        base_bonus = _draw_pool(base_rng, game.bonus, bonus_w or _uniform(game.bonus), 1, [], True, 0.0)[0]

    last_reason = None
    for attempt in range(1, max_attempts + 1):
        if req.mode == "drift" and req.strategy != "pure":
            main = _drift(rng, game.main, base_main, t, game.main.distinct, exclude)
            for n in req.locked:
                if n not in main:
                    main = sorted(set(main[:-1]) | {n}) if game.main.distinct else main
            bonus = None
            if game.bonus:
                bonus = _drift(rng, game.bonus, [base_bonus], t, True, set())[0]
        else:
            if pos_w:
                main = [_draw_pool(rng, game.main, blend(w, t), 1, [], False, t)[0] for w in pos_w]
            else:
                mw = blend(main_w, t)
                main = _draw_pool(rng, game.main, mw, req.count, req.locked, game.main.distinct, t)
            bonus = None
            if game.bonus:
                bw = blend(bonus_w or _uniform(game.bonus), t)
                bonus = _draw_pool(rng, game.bonus, bw, 1, [], True, t)[0]
        reason = check_filters(game, main, bonus, req.filters, stats)
        if reason is None:
            return Pick(game.key, main, bonus, req.strategy, t, req.mode, list(req.filters), attempt,
                        base_main, base_bonus, notes)
        last_reason = reason
        if t <= 0.0:
            # deterministic base can't change; let the filter loosen by nudging entropy slightly
            t = 0.05
    raise RuntimeError(f"no pick passed the filters after {max_attempts} tries (last: {last_reason})")


def batch(req: PickRequest, seed: bytes, n: int, max_shared: int = 2, stats: dict | None = None) -> list[Pick]:
    """Generate n tickets where no two share more than max_shared main numbers."""
    picks: list[Pick] = []
    tries = 0
    while len(picks) < n and tries < n * 60:
        tries += 1
        sub_seed = hashlib.sha256(seed + tries.to_bytes(4, "big")).digest()
        p = generate(req, sub_seed, stats)
        if all(len(set(p.main) & set(q.main)) <= max_shared for q in picks):
            picks.append(p)
    if len(picks) < n:
        raise RuntimeError(f"could only build {len(picks)} of {n} tickets with at most {max_shared} shared numbers")
    return picks
