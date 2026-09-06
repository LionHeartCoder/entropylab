"""Match saved tickets against official results."""
from __future__ import annotations
import sqlite3

from .feeds import Draw, get_draws
from .games import GAMES
from .history import list_tickets, update_ticket

# Prize labels by (main matched, bonus matched). Verify amounts on valottery.com; these are the published tiers.
PRIZES: dict[str, dict[tuple[int, bool], str]] = {
    "powerball": {
        (5, True): "JACKPOT", (5, False): "$1,000,000", (4, True): "$50,000", (4, False): "$100",
        (3, True): "$100", (3, False): "$7", (2, True): "$7", (1, True): "$4", (0, True): "$4",
    },
    "megamillions": {
        (5, True): "JACKPOT", (5, False): "$1,000,000", (4, True): "$10,000", (4, False): "$500",
        (3, True): "$200", (3, False): "$10", (2, True): "$10", (1, True): "$7", (0, True): "$5",
    },
    "millionaireforlife": {
        (5, True): "$1,000/day for life", (5, False): "$1,000/week for life", (4, True): "$2,500",
        (4, False): "$500", (3, True): "$100", (3, False): "$25", (2, True): "$10", (1, True): "$4", (0, True): "$2",
    },
    "cash5": {(5, False): "$100,000", (4, False): "$100", (3, False): "$10", (2, False): "$1"},
}


def match_counts(game_key: str, main: list[int], bonus: int | None, draw: Draw) -> tuple[int, bool, str]:
    g = GAMES[game_key]
    if not g.main.distinct:
        # digit games: exact-order digit matches
        exact = sum(1 for a, b in zip(main, draw.main) if a == b)
        any_order = main == draw.main and True
        if list(main) == list(draw.main):
            label = "EXACT MATCH"
        elif sorted(main) == sorted(draw.main):
            label = "any-order match"
        else:
            label = f"{exact} digit{'s' if exact != 1 else ''} in place"
        return exact, False, label
    if game_key == "cashpop":
        hit = draw.main[0] in main
        return (1 if hit else 0), False, ("POP! matched" if hit else "missed")
    if game_key == "bankamillion":
        m = len(set(main) & set(draw.main))
        b = draw.bonus in main if draw.bonus is not None else False
        label = {6: "$1,000,000 (at $2)", 5: "$1,000" if not b else "$1,500", 4: "$25" if not b else "$100"}.get(m, "")
        if not label:
            label = f"{m} of 6"
        return m, b, label
    m = len(set(main) & set(draw.main))
    b = bonus is not None and draw.bonus is not None and bonus == draw.bonus
    table = PRIZES.get(game_key, {})
    label = table.get((m, b))
    if not label:
        label = f"{m} of {len(draw.main)}" + (" + bonus" if b else "")
    return m, b, label


def find_draw(game_key: str, target_date: str | None, session: str, created: float) -> Draw | None:
    from datetime import datetime, timezone
    draws = get_draws(game_key)
    if target_date:
        for d in draws:
            if d.date == target_date and (not session or d.session == session):
                return d
        return None
    created_date = datetime.fromtimestamp(created, tz=timezone.utc).date().isoformat()
    later = [d for d in draws if d.date >= created_date]
    return later[-1] if later else None


def check_all(con: sqlite3.Connection, game: str | None = None, owner: str | None = None) -> dict:
    tickets = list_tickets(con, game=game, limit=10_000, unchecked_only=True, owner=owner)
    checked, pending, errors = [], [], []
    for t in tickets:
        gk = t["game"]
        if GAMES[gk].feed_id is None:
            continue
        try:
            d = find_draw(gk, t.get("target_date"), t.get("session") or "", t["created"])
        except Exception as e:  # noqa: BLE001
            errors.append({"id": t["id"], "error": str(e)})
            continue
        if d is None:
            pending.append(t["id"])
            continue
        m, b, label = match_counts(gk, t["main"], t.get("bonus"), d)
        update_ticket(con, t["id"], checked_date=d.date, checked_session=d.session, match_main=m,
                      match_bonus=int(b), result_main=d.main, result_bonus=d.bonus, prize=label)
        checked.append({"id": t["id"], "game": gk, "match_main": m, "match_bonus": b, "prize": label,
                        "result_main": d.main, "result_bonus": d.bonus, "date": d.date, "session": d.session})
    return {"checked": checked, "pending": pending, "errors": errors}
