"""Next-draw calculation for each game, in US Eastern time."""
from __future__ import annotations
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo

from .games import GAMES, Game

ET = ZoneInfo("America/New_York")
DAYS = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}

# (time, session label) per game
SESSIONS: dict[str, list[tuple[dtime, str]]] = {
    "powerball": [(dtime(23, 0), "")],
    "megamillions": [(dtime(23, 0), "")],
    "millionaireforlife": [(dtime(23, 15), "")],
    "bankamillion": [(dtime(23, 0), "")],
    "cash5": [(dtime(23, 0), "")],
    "pick3": [(dtime(13, 59), "day"), (dtime(23, 0), "night")],
    "pick4": [(dtime(13, 59), "day"), (dtime(23, 0), "night")],
    "pick5": [(dtime(13, 59), "day"), (dtime(23, 0), "night")],
    "cashpop": [
        (dtime(9, 0), "Coffee Break"), (dtime(12, 0), "Lunch Break"), (dtime(17, 0), "Rush Hour"),
        (dtime(21, 0), "Prime Time"), (dtime(23, 59), "After Hours"),
    ],
}
# sales cutoff minutes before the draw
CUTOFF_MIN = {"powerball": 60, "megamillions": 60, "millionaireforlife": 60, "bankamillion": 60, "cash5": 15,
              "pick3": 10, "pick4": 10, "pick5": 10, "cashpop": 1}


def _weekdays(game: Game) -> set[int] | None:
    if game.draw_days.lower().startswith("daily"):
        return None
    return {DAYS[d.strip()] for d in game.draw_days.split(",")}


def next_draw(game_key: str, now: datetime | None = None) -> dict | None:
    """Return {'date': ISO, 'session': str, 'at': ISO datetime, 'seconds': int} for the next open draw."""
    game = GAMES[game_key]
    if game_key not in SESSIONS:
        return None
    now = (now or datetime.now(ET)).astimezone(ET)
    wd = _weekdays(game)
    cutoff = timedelta(minutes=CUTOFF_MIN.get(game_key, 0))
    for day_off in range(0, 9):
        d = (now + timedelta(days=day_off)).date()
        if wd is not None and d.weekday() not in wd:
            continue
        for t, session in SESSIONS[game_key]:
            at = datetime.combine(d, t, tzinfo=ET)
            if at - cutoff > now:
                return {
                    "date": d.isoformat(),
                    "session": session,
                    "at": at.isoformat(),
                    "seconds": int((at - now).total_seconds()),
                    "sales_close": (at - cutoff).isoformat(),
                }
    return None


def all_next_draws(now: datetime | None = None) -> dict[str, dict | None]:
    return {k: next_draw(k, now) for k in GAMES}
