"""Winning-number feeds.

Primary: valottery.com plain-text download (same file as the site's
"download all results" button) for every game except Keno.
Backup: New York open data for Powerball and Mega Millions.
"""
from __future__ import annotations
import json
import re
import time
from dataclasses import dataclass, asdict
from datetime import date, datetime
from pathlib import Path

import httpx

from .games import GAMES, Game

VA_URL = "https://www.valottery.com/api/v1/downloadall"
NY_URLS = {
    "powerball": "https://data.ny.gov/resource/d6yy-54nr.json",
    "megamillions": "https://data.ny.gov/resource/5xaw-6ayf.json",
}
UA = {"User-Agent": "Mozilla/5.0 (entropy-lab local lottery tool)"}
import os
CACHE_DIR = Path(os.environ.get("LOTTO_DATA_DIR") or Path(__file__).resolve().parents[2] / "data") / "feeds"


@dataclass
class Draw:
    game: str
    date: str            # ISO date
    session: str         # "", "day", "night", or Cash Pop draw name
    main: list[int]
    bonus: int | None = None
    fireball: int | None = None

    def as_dict(self) -> dict:
        return asdict(self)


_BONUS_WORDS = ("Powerball", "Mega Ball", "Money Ball", "Millionaire Ball", "Bonus Ball", "Bonus", "Fireball")


def _iso(mdy: str) -> str:
    m, d, y = mdy.strip().split("/")
    return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"


def _nums(s: str) -> list[int]:
    return [int(x) for x in re.findall(r"\d+", s)]


def parse_va_feed(game: Game, text: str) -> list[Draw]:
    """Parse the semicolon-separated valottery download text into Draw rows."""
    draws: list[Draw] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.lower().startswith("results for"):
            continue
        parts = [p.strip() for p in line.split(";") if p.strip()]
        if len(parts) < 2:
            continue
        head = parts[0]

        if game.key == "cashpop":
            # "Sun 09/06/2026 - 12:00 PM; 1; Lunch Break"
            m = re.search(r"(\d{1,2}/\d{1,2}/\d{4})", head)
            if not m:
                continue
            draws.append(Draw(game.key, _iso(m.group(1)), parts[2] if len(parts) > 2 else "", [int(parts[1])]))
            continue

        if not re.match(r"\d{1,2}/\d{1,2}/\d{4}$", head):
            continue
        iso = _iso(head)

        if game.key in ("pick3", "pick4", "pick5"):
            # "9/5/2026; Day: 8,1,7; Fireball: 5; Night: 9,3,7; Fireball: 5"   (old rows: "Night: 9,1,4")
            session = None
            digits: list[int] = []
            fireball = None
            for p in parts[1:]:
                if p.startswith("Day:") or p.startswith("Night:"):
                    if session is not None and digits:
                        draws.append(Draw(game.key, iso, session, digits, None, fireball))
                    session = "day" if p.startswith("Day:") else "night"
                    digits = _nums(p)
                    fireball = None
                elif p.startswith("Fireball:"):
                    fb = _nums(p)
                    fireball = fb[0] if fb else None
            if session is not None and digits:
                draws.append(Draw(game.key, iso, session, digits, None, fireball))
            continue

        # jackpot-style rows: "9/5/2026; 15,40,47,53,59; Powerball: 9"  or Cash 5 old rows "2/5/1993; Night: 15,18,27,31,32"
        session = ""
        main: list[int] = []
        bonus = None
        for p in parts[1:]:
            if any(p.startswith(w) for w in _BONUS_WORDS):
                b = _nums(p)
                bonus = b[0] if b else None
            elif p.startswith("Day:") or p.startswith("Night:"):
                if main:
                    draws.append(Draw(game.key, iso, session, main, bonus))
                    bonus = None
                session = "day" if p.startswith("Day:") else "night"
                main = _nums(p)
            elif not main:
                main = _nums(p)
        if main:
            draws.append(Draw(game.key, iso, session, main, bonus))
    return draws


def fetch_va(game: Game, timeout: float = 60) -> str:
    if game.feed_id is None:
        raise RuntimeError(f"{game.name} has no results feed")
    r = httpx.get(VA_URL, params={"gameId": game.feed_id}, headers=UA, timeout=timeout, follow_redirects=True)
    r.raise_for_status()
    if "<html" in r.text[:200].lower():
        raise RuntimeError(f"feed for {game.name} returned an HTML error page")
    return r.text


def fetch_ny(game_key: str, timeout: float = 60) -> list[Draw]:
    url = NY_URLS[game_key]
    r = httpx.get(url, params={"$limit": 5000, "$order": "draw_date DESC"}, timeout=timeout)
    r.raise_for_status()
    out = []
    for row in r.json():
        nums = _nums(row["winning_numbers"])
        bonus = nums[-1] if len(nums) == 6 else (int(row.get("mega_ball", 0)) or None)
        main = nums[:5]
        out.append(Draw(game_key, row["draw_date"][:10], "", main, bonus))
    return out


def cache_path(game_key: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{game_key}.json"


def load_cached(game_key: str) -> tuple[list[Draw], float | None]:
    p = cache_path(game_key)
    if not p.exists():
        return [], None
    j = json.loads(p.read_text(encoding="utf-8"))
    return [Draw(**d) for d in j["draws"]], j.get("fetched")


def save_cache(game_key: str, draws: list[Draw]) -> None:
    cache_path(game_key).write_text(
        json.dumps({"fetched": time.time(), "draws": [d.as_dict() for d in draws]}), encoding="utf-8"
    )


def get_draws(game_key: str, max_age_hours: float = 6, force: bool = False) -> list[Draw]:
    """Return the full draw history, newest first, refreshing from the feed when stale."""
    game = GAMES[game_key]
    cached, fetched = load_cached(game_key)
    fresh = fetched is not None and (time.time() - fetched) < max_age_hours * 3600
    if cached and fresh and not force:
        return cached
    try:
        draws = parse_va_feed(game, fetch_va(game))
    except Exception as e:  # noqa: BLE001
        if game_key in NY_URLS:
            try:
                draws = fetch_ny(game_key)
            except Exception:  # noqa: BLE001
                draws = []
        else:
            draws = []
        if not draws:
            if cached:
                return cached
            raise RuntimeError(f"could not fetch results for {game.name}: {e}") from e
    draws.sort(key=lambda d: (d.date, d.session), reverse=True)
    save_cache(game_key, draws)
    return draws


def latest_draw(game_key: str, session: str | None = None) -> Draw | None:
    for d in get_draws(game_key):
        if session is None or d.session == session:
            return d
    return None
