"""SQLite ticket log. Every pick stores the pool seed hash and the sources that fed it."""
from __future__ import annotations
import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path

DATA_DIR = Path(os.environ.get("LOTTO_DATA_DIR") or Path(__file__).resolve().parents[2] / "data")
DB_PATH = DATA_DIR / "lotto.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created REAL NOT NULL,
    game TEXT NOT NULL,
    main TEXT NOT NULL,
    bonus INTEGER,
    strategy TEXT NOT NULL,
    entropy REAL NOT NULL,
    mode TEXT NOT NULL,
    filters TEXT NOT NULL,
    sources TEXT NOT NULL,
    seed_hash TEXT NOT NULL,
    bits_in INTEGER NOT NULL,
    shadow INTEGER NOT NULL DEFAULT 0,
    label TEXT DEFAULT '',
    target_date TEXT,
    session TEXT DEFAULT '',
    checked_date TEXT,
    checked_session TEXT,
    match_main INTEGER,
    match_bonus INTEGER,
    result_main TEXT,
    result_bonus INTEGER,
    prize TEXT
);
CREATE TABLE IF NOT EXISTS pools (
    seed_hash TEXT PRIMARY KEY,
    created REAL NOT NULL,
    detail TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def connect(path: Path | None = None) -> sqlite3.Connection:
    p = path or DB_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    cols = {r[1] for r in con.execute("PRAGMA table_info(tickets)")}
    if "owner" not in cols:
        con.execute("ALTER TABLE tickets ADD COLUMN owner TEXT NOT NULL DEFAULT 'local'")
        con.execute("CREATE INDEX IF NOT EXISTS idx_tickets_owner ON tickets(owner)")
        con.commit()
    return con


def seed_hash(seed: bytes) -> str:
    return hashlib.sha256(b"receipt" + seed).hexdigest()[:24]


def save_pool(con: sqlite3.Connection, pool_dict: dict) -> str:
    sh = seed_hash(bytes.fromhex(pool_dict["seed"]))
    detail = {k: v for k, v in pool_dict.items() if k != "seed"}
    con.execute("INSERT OR IGNORE INTO pools(seed_hash, created, detail) VALUES (?,?,?)",
                (sh, pool_dict.get("created", time.time()), json.dumps(detail)))
    con.commit()
    return sh


def save_ticket(con: sqlite3.Connection, pick: dict, sources: list[str], sh: str, bits_in: int,
                shadow: bool = False, label: str = "", target_date: str | None = None, session: str = "",
                owner: str = "local") -> int:
    cur = con.execute(
        """INSERT INTO tickets(created, game, main, bonus, strategy, entropy, mode, filters, sources, seed_hash,
           bits_in, shadow, label, target_date, session, owner) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (time.time(), pick["game"], json.dumps(pick["main"]), pick.get("bonus"), pick["strategy"], pick["entropy"],
         pick["mode"], json.dumps(pick.get("filters", [])), json.dumps(sources), sh, bits_in, int(shadow), label,
         target_date, session, owner),
    )
    con.commit()
    return cur.lastrowid


def _row(r: sqlite3.Row) -> dict:
    d = dict(r)
    for k in ("main", "filters", "sources", "result_main"):
        if d.get(k):
            d[k] = json.loads(d[k])
    return d


def list_tickets(con: sqlite3.Connection, game: str | None = None, limit: int = 200, unchecked_only: bool = False,
                 owner: str | None = None) -> list[dict]:
    q = "SELECT * FROM tickets"
    cond, args = [], []
    if owner is not None:
        cond.append("owner = ?"); args.append(owner)
    if game:
        cond.append("game = ?"); args.append(game)
    if unchecked_only:
        cond.append("checked_date IS NULL")
    if cond:
        q += " WHERE " + " AND ".join(cond)
    q += " ORDER BY id DESC LIMIT ?"
    args.append(limit)
    return [_row(r) for r in con.execute(q, args)]


def get_ticket(con: sqlite3.Connection, tid: int) -> dict | None:
    r = con.execute("SELECT * FROM tickets WHERE id = ?", (tid,)).fetchone()
    return _row(r) if r else None


def delete_ticket(con: sqlite3.Connection, tid: int, owner: str | None = None) -> None:
    if owner is None:
        con.execute("DELETE FROM tickets WHERE id = ?", (tid,))
    else:
        con.execute("DELETE FROM tickets WHERE id = ? AND owner = ?", (tid, owner))
    con.commit()


def update_ticket(con: sqlite3.Connection, tid: int, **fields) -> None:
    if not fields:
        return
    for k in ("result_main",):
        if k in fields and fields[k] is not None:
            fields[k] = json.dumps(fields[k])
    sets = ", ".join(f"{k} = ?" for k in fields)
    con.execute(f"UPDATE tickets SET {sets} WHERE id = ?", (*fields.values(), tid))
    con.commit()


def get_pool(con: sqlite3.Connection, sh: str) -> dict | None:
    r = con.execute("SELECT * FROM pools WHERE seed_hash = ?", (sh,)).fetchone()
    if not r:
        return None
    return {"seed_hash": r["seed_hash"], "created": r["created"], **json.loads(r["detail"])}


def get_setting(con: sqlite3.Connection, key: str, default=None):
    r = con.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return json.loads(r["value"]) if r else default


def set_setting(con: sqlite3.Connection, key: str, value) -> None:
    con.execute("INSERT OR REPLACE INTO settings(key, value) VALUES (?,?)", (key, json.dumps(value)))
    con.commit()


def trophies(con: sqlite3.Connection, owner: str | None = None) -> dict:
    if owner is None:
        rows = [_row(r) for r in con.execute("SELECT * FROM tickets")]
    else:
        rows = [_row(r) for r in con.execute("SELECT * FROM tickets WHERE owner = ?", (owner,))]
    checked = [r for r in rows if r.get("checked_date")]
    by_source: dict[str, int] = {}
    for r in rows:
        for s in r.get("sources", []):
            by_source[s] = by_source.get(s, 0) + 1
    best = None
    for r in checked:
        score = (r.get("match_main") or 0) + (0.5 if r.get("match_bonus") else 0)
        if best is None or score > best[0]:
            best = (score, r)
    streak = 0
    for r in sorted(checked, key=lambda r: r["id"], reverse=True):
        if (r.get("match_main") or 0) > 0 or r.get("match_bonus"):
            streak += 1
        else:
            break
    return {
        "tickets": len(rows),
        "shadow_tickets": sum(1 for r in rows if r.get("shadow")),
        "checked": len(checked),
        "any_match": sum(1 for r in checked if (r.get("match_main") or 0) > 0 or r.get("match_bonus")),
        "bits_consumed": sum(r.get("bits_in") or 0 for r in rows),
        "favorite_source": max(by_source, key=by_source.get) if by_source else None,
        "source_counts": by_source,
        "closest_miss": best[1] if best else None,
        "current_streak": streak,
    }
