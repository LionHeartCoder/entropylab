# Entropy Lab

Multi-source true-random lottery picker for Virginia Lottery draw games, with a live
web UI, ticket log, official-results checker, history research, and a strategy arena.

## Run it

Double-click `Entropy Lab.cmd`, or from a terminal in this folder:

```
uv run lotto serve
```

The browser opens at http://127.0.0.1:8765. Everything runs on your machine.
Windows will ask for camera and microphone permission the first time.

Command-line fallback:

```
uv run lotto games
uv run lotto pick powerball --sources cpu,camera,mic,anu,nist
uv run lotto pick cash5 --strategy hot --entropy 0.5 --tickets 5
uv run lotto check
uv run lotto stats cash5
uv run lotto arena powerball
```

## How the randomness works

1. Each selected source is read on its own: CPU hardware RNG (RDSEED via Windows),
   webcam frame-difference noise, microphone low bits, ANU quantum vacuum API,
   NIST randomness beacon, your mouse scribbles, and an optional phrase.
2. Every source is hashed with SHA-256 separately, then the digests are hashed together
   with a domain tag and a timestamp into a 32-byte seed. Any single unpredictable source
   makes the seed unpredictable.
3. The seed drives a ChaCha20 keystream. Numbers are drawn by rejection sampling, so
   no value in a range is favored.
4. Every ticket stores a receipt hash of the pool and the list of sources that fed it.

## Pick methods

* Pure entropy, hot numbers, cold numbers, most-drawn pairs, lucky numbers with locks,
  phrase seed.
* Entropy influence slider: at 0 % you get the base pick, at 100 % pure entropy.
  Weight blend mixes the base weights toward flat; drift rolls each base number a
  random distance.
* Filters: anti-split (no all-birthday picks), anti-pattern, balanced, never-hit.
* Batches with a cap on shared numbers, shadow tickets, wheeling systems.

## Tools tab

The same entropy pool drives general-purpose generators: integers, decimals, dice,
coins, list shuffles and picks, passwords (custom classes, look-alike exclusion, extra
characters), EFF diceware passphrases, PINs, hex/base64 keys, and UUIDs. Results show
their entropy in bits and are never saved.

Encrypt/decrypt uses AES-256-GCM with a scrypt-derived key. Tokens look like
`elab1.<salt>.<nonce>.<ciphertext>` and are self-contained.

A desktop shortcut (`Entropy Lab.lnk`) points at the launcher.

## Honest note

Every draw is independent. No picking method changes your odds. The one real effect of
random picks is avoiding popular birthday-style combinations, which lowers the chance of
splitting a jackpot. Hot and cold numbers are for fun; the arena tab shows every method
converging on the same average when backtested on real history.

## Data

* Results come from valottery.com's plain-text download feed (all games except Keno),
  cached in `data/feeds/`. New York open data is the fallback for Powerball and Mega Millions.
* Tickets and settings live in `data/lotto.db` (SQLite).

## Layout

```
src/lotto/
  games.py       rules for every VA draw game
  rng.py         ChaCha20 DRBG with rejection sampling
  entropy/       one module per source, pool.py combines them
  picker.py      strategies, slider, filters, batches
  feeds.py       results download and parsing
  stats.py       hot/cold/pairs/sums, era filtering
  checker.py     ticket vs. result matching and prize tiers
  arena.py       strategy backtest
  wheel.py       full, abbreviated, and key wheels
  health.py      randomness tests
  schedule.py    next-draw countdown
  history.py     SQLite ticket log and trophies
  web/           FastAPI server and the single-page UI
tests/           pytest suite
```
