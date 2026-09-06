"""Virginia Lottery draw-game rules, verified against valottery.com on 2026-09-06."""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Pool:
    """One set of balls: pick `count` numbers from lo..hi (inclusive)."""
    name: str
    lo: int
    hi: int
    count: int
    distinct: bool = True
    user_sets_count: bool = False   # Keno / Cash Pop: player chooses how many
    min_count: int = 1
    max_count: int = 1

    @property
    def size(self) -> int:
        return self.hi - self.lo + 1


@dataclass(frozen=True)
class Game:
    key: str
    name: str
    pools: tuple[Pool, ...]
    feed_id: int | None            # valottery downloadall gameId
    draw_days: str
    draw_times: tuple[str, ...]
    price: str
    era_start: str | None = None   # first draw date under the current rules (for stats)
    notes: str = ""

    @property
    def main(self) -> Pool:
        return self.pools[0]

    @property
    def bonus(self) -> Pool | None:
        return self.pools[1] if len(self.pools) > 1 else None


GAMES: dict[str, Game] = {
    "powerball": Game(
        "powerball", "Powerball",
        (Pool("main", 1, 69, 5), Pool("Powerball", 1, 26, 1)),
        feed_id=20, draw_days="Mon, Wed, Sat", draw_times=("23:00",), price="$2",
        era_start="2015-10-07", notes="Power Play add-on $1",
    ),
    "megamillions": Game(
        "megamillions", "Mega Millions",
        (Pool("main", 1, 70, 5), Pool("Mega Ball", 1, 24, 1)),
        feed_id=15, draw_days="Tue, Fri", draw_times=("23:00",), price="$5",
        era_start="2025-04-08",
    ),
    "millionaireforlife": Game(
        "millionaireforlife", "Millionaire for Life",
        (Pool("main", 1, 58, 5), Pool("Millionaire Ball", 1, 5, 1)),
        feed_id=1075, draw_days="Daily", draw_times=("23:15",), price="$5",
        era_start="2026-02-22",
    ),
    "bankamillion": Game(
        "bankamillion", "Bank a Million",
        (Pool("main", 1, 40, 6),),
        feed_id=1070, draw_days="Wed, Sat", draw_times=("23:00",), price="$2",
        era_start="2015-09-02", notes="Bonus Ball drawn by lottery, not picked",
    ),
    "cash5": Game(
        "cash5", "Cash 5",
        (Pool("main", 1, 45, 5),),
        feed_id=1030, draw_days="Daily", draw_times=("23:00",), price="$1",
        era_start="2021-04-04", notes="EZ Match add-on $1",
    ),
    "pick3": Game(
        "pick3", "Pick 3",
        (Pool("digits", 0, 9, 3, distinct=False),),
        feed_id=1050, draw_days="Daily", draw_times=("13:59", "23:00"), price="$0.50-$1",
        notes="Fireball add-on",
    ),
    "pick4": Game(
        "pick4", "Pick 4",
        (Pool("digits", 0, 9, 4, distinct=False),),
        feed_id=1040, draw_days="Daily", draw_times=("13:59", "23:00"), price="$0.50-$1",
        notes="Fireball add-on",
    ),
    "pick5": Game(
        "pick5", "Pick 5",
        (Pool("digits", 0, 9, 5, distinct=False),),
        feed_id=1035, draw_days="Daily", draw_times=("13:59", "23:00"), price="$1",
        notes="Fireball add-on",
    ),
    "cashpop": Game(
        "cashpop", "Cash Pop",
        (Pool("main", 1, 15, 1, user_sets_count=True, min_count=1, max_count=15),),
        feed_id=40, draw_days="Daily", draw_times=("09:00", "12:00", "17:00", "21:00", "23:59"),
        price="$1-$10 per number",
    ),
    "keno": Game(
        "keno", "Keno",
        (Pool("main", 1, 80, 10, user_sets_count=True, min_count=1, max_count=10),),
        feed_id=None, draw_days="Daily", draw_times=("every 4 min",), price="$1-$10",
        notes="20 numbers drawn; results feed not available",
    ),
}


def get_game(key: str) -> Game:
    try:
        return GAMES[key]
    except KeyError:
        raise KeyError(f"unknown game '{key}'; choose from {', '.join(GAMES)}") from None
