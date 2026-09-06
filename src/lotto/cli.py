"""Command-line fallback: `lotto pick powerball`, `lotto serve`, `lotto check`, `lotto stats cash5`."""
from __future__ import annotations
import os

import typer

from . import history
from .entropy import DEFAULT_SOURCES, collect
from .games import GAMES
from .picker import PickRequest, batch, generate

app = typer.Typer(add_completion=False, help="Entropy Lab lottery picker")


@app.command()
def games():
    """List supported games."""
    for k, g in GAMES.items():
        pools = " + ".join(f"{p.count} of {p.lo}-{p.hi}" for p in g.pools)
        typer.echo(f"{k:20s} {g.name:22s} {pools:28s} {g.draw_days} {', '.join(g.draw_times)}")


@app.command()
def pick(
    game: str = typer.Argument(..., help="game key, see `lotto games`"),
    sources: str = typer.Option(",".join(DEFAULT_SOURCES), help="comma-separated entropy sources"),
    strategy: str = "pure",
    entropy: float = 1.0,
    mode: str = "blend",
    tickets: int = 1,
    count: int | None = typer.Option(None, help="Keno / Cash Pop: how many numbers"),
    lucky: str = typer.Option("", help="comma-separated lucky numbers"),
    locked: str = "",
    exclude: str = "",
    filters: str = typer.Option("", help="comma-separated: anti_split,anti_pattern,balanced,never_hit"),
    phrase: str = "",
    save: bool = True,
    shadow: bool = False,
):
    """Generate one or more picks."""
    ints = lambda s: [int(x) for x in s.split(",") if x.strip()]  # noqa: E731
    keys = [s.strip() for s in sources.split(",") if s.strip()]
    typer.echo(f"gathering entropy from {', '.join(keys)} ...")
    pool = collect(keys, progress=lambda k, i, n: None)
    for r in pool.results:
        mark = "ok " if r.ok else "ERR"
        typer.echo(f"  [{mark}] {r.key:8s} {r.raw_len:6d} B  {r.entropy_bits_per_byte:4.2f} bits/B  {r.elapsed_ms:5d} ms  {r.detail or r.error}")
    req = PickRequest(game, count=count, strategy=strategy, entropy=entropy, mode=mode, lucky=ints(lucky),
                      locked=ints(locked), exclude=ints(exclude), filters=[f for f in filters.split(",") if f], phrase=phrase)
    picks = [generate(req, pool.seed)] if tickets == 1 else batch(req, pool.seed, tickets)
    con = history.connect()
    sh = history.save_pool(con, pool.as_dict())
    from .schedule import next_draw
    nd = next_draw(game)
    for p in picks:
        tid = history.save_ticket(con, p.as_dict(), pool.ok_sources, sh, pool.bits_in, shadow=shadow,
                                  target_date=nd["date"] if nd else None, session=nd["session"] if nd else "") if save else None
        typer.echo(f"{GAMES[game].name}: {p.display()}   (ticket #{tid}, receipt {sh})" if tid else f"{GAMES[game].name}: {p.display()}")


@app.command()
def check():
    """Check saved tickets against official results."""
    from .checker import check_all
    res = check_all(history.connect())
    for c in res["checked"]:
        typer.echo(f"ticket #{c['id']:4d} {c['game']:18s} {c['date']} {c['session']:6s} matched {c['match_main']}"
                   f"{' + bonus' if c['match_bonus'] else ''}  -> {c['prize']}")
    typer.echo(f"{len(res['checked'])} checked, {len(res['pending'])} waiting for a draw")


@app.command()
def stats(game: str, era: bool = True):
    """Hot and cold numbers for a game."""
    from .stats import game_stats
    s = game_stats(game, current_era=era)
    if not s["available"]:
        typer.echo(s["reason"]); return
    typer.echo(f"{GAMES[game].name}: {s['draws_used']} draws used of {s['draws_total']} ({s['first_date']} to {s['last_date']})")
    typer.echo(f"hot : {s['main']['hot']}")
    typer.echo(f"cold: {s['main']['cold']}")
    if "bonus" in s:
        typer.echo(f"bonus hot {s['bonus']['hot']}  cold {s['bonus']['cold']}")


@app.command()
def arena(game: str, n: int = 300, window: int = 200, entropy: float = 0.3):
    """Backtest strategies against real history."""
    from .arena import run_arena
    a = run_arena(game, n_draws=n, window=window, entropy=entropy, seed=os.urandom(32))
    if not a["available"]:
        typer.echo(a["reason"]); return
    typer.echo(f"{GAMES[game].name}: {a['draws_tested']} draws, expected average match {a['expected_avg_match']}")
    for s in a["leaderboard"]:
        r = a["results"][s]
        typer.echo(f"  {s:9s} avg {r['avg_match']:.3f}   3+ matches {r['three_plus']}")


@app.command()
def serve(port: int = 8765, no_browser: bool = False):
    """Start the Entropy Lab web UI."""
    from .web.app import main
    main(port=port, open_browser=not no_browser)


if __name__ == "__main__":
    app()
