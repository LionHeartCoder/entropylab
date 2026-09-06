"""Entropy Lab local web server (FastAPI). Runs on localhost only."""
from __future__ import annotations
import asyncio
import base64
import hashlib
import json
import threading
import time
from pathlib import Path

import uuid

from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .. import arena as arena_mod
from .. import checker, history, schedule, stats as stats_mod, tools as tools_mod, wheel as wheel_mod
from ..entropy import DEFAULT_SOURCES, REGISTRY, collect
from ..entropy.pool import HOSTED
from ..games import GAMES
from ..health import health_report
from ..picker import FILTERS, MODES, STRATEGIES, PickRequest, batch, generate

STATIC = Path(__file__).parent / "static"
app = FastAPI(title="Entropy Lab")
con = history.connect()
_camera_lock = threading.Lock()
OWNER_COOKIE = "elab_owner"


def owner_of(req) -> str:
    """Local mode: one shared owner. Hosted mode: an anonymous id stored in a cookie."""
    if not HOSTED:
        return "local"
    return req.cookies.get(OWNER_COOKIE) or "anon"


@app.middleware("http")
async def _owner_cookie(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = ("public, max-age=31536000, immutable" if request.query_params.get("v") == ASSET_VERSION
                                             else "no-cache")
    elif request.url.path.startswith("/api/") or request.url.path == "/healthz":
        response.headers["Cache-Control"] = "no-store"
    if HOSTED and not request.cookies.get(OWNER_COOKIE):
        response.set_cookie(OWNER_COOKIE, uuid.uuid4().hex, max_age=10 * 365 * 24 * 3600, samesite="lax", httponly=True)
    return response


def game_info(k: str) -> dict:
    g = GAMES[k]
    return {
        "key": k, "name": g.name, "price": g.price, "draw_days": g.draw_days, "draw_times": g.draw_times,
        "notes": g.notes, "era_start": g.era_start, "has_feed": g.feed_id is not None,
        "pools": [
            {"name": p.name, "lo": p.lo, "hi": p.hi, "count": p.count, "distinct": p.distinct,
             "user_sets_count": p.user_sets_count, "min_count": p.min_count, "max_count": p.max_count}
            for p in g.pools
        ],
        "next": schedule.next_draw(k),
    }


def _asset_version() -> str:
    h = hashlib.sha256()
    for name in ("app.js", "style.css", "index.html"):
        h.update((STATIC / name).read_bytes())
    return h.hexdigest()[:10]


ASSET_VERSION = _asset_version()


@app.get("/")
def index():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    html = html.replace('static/style.css"', f'static/style.css?v={ASSET_VERSION}"').replace(
        'static/app.js"', f'static/app.js?v={ASSET_VERSION}"')
    return Response(html, media_type="text/html", headers={"Cache-Control": "no-cache"})


@app.get("/api/meta")
def meta(request: Request):
    return {
        "games": [game_info(k) for k in GAMES],
        "sources": [s.info() for s in REGISTRY.values()],
        "default_sources": DEFAULT_SOURCES,
        "strategies": STRATEGIES, "filters": FILTERS, "modes": MODES,
        "settings": history.get_setting(con, "ui:" + owner_of(request), {}),
        "hosted": HOSTED,
    }


@app.post("/api/settings")
async def save_settings(body: dict, request: Request):
    history.set_setting(con, "ui:" + owner_of(request), body)
    return {"ok": True}


@app.get("/api/next")
def next_draws():
    return schedule.all_next_draws()


# ------------------------------------------------------------------ generation over websocket

def _pick_request(body: dict) -> PickRequest:
    return PickRequest(
        game=body["game"],
        count=body.get("count"),
        strategy=body.get("strategy", "pure"),
        entropy=float(body.get("entropy", 1.0)),
        mode=body.get("mode", "blend"),
        lucky=[int(x) for x in body.get("lucky", [])],
        locked=[int(x) for x in body.get("locked", [])],
        lucky_bonus=body.get("lucky_bonus"),
        exclude=[int(x) for x in body.get("exclude", [])],
        filters=list(body.get("filters", [])),
        phrase=body.get("phrase", ""),
        current_era=bool(body.get("current_era", True)),
    )


def _gather(body: dict, emit):
    """Collect entropy from the requested sources, streaming progress events. Shared by all websockets."""
    sources = [s for s in body.get("sources", DEFAULT_SOURCES) if s in REGISTRY]
    if not sources:
        raise ValueError("select at least one entropy source")
    opts: dict = {}
    for cam in ("camera", "camera1"):
        opts[cam] = {"frames": int(body.get("frames", 24)),
                     "preview": (lambda c: lambda jpg, i, n: emit({"type": "frame", "source": c, "i": i, "n": n,
                                                                    "jpeg": base64.b64encode(jpg).decode()}))(cam)}
    opts["mic"] = {"seconds": float(body.get("mic_seconds", 1.0)),
                   "waveform": lambda w: emit({"type": "waveform", "samples": w})}
    opts["mouse"] = {"events": body.get("mouse_events", [])}
    opts["phrase"] = {"phrase": body.get("phrase", "")}
    file_b64 = body.get("file_b64")
    opts["file"] = {"data": base64.b64decode(file_b64) if file_b64 else None, "filename": body.get("file_name", "")}
    opts["webcam"] = {"frames": [base64.b64decode(f) for f in body.get("webcam_frames", [])]}
    opts["audio"] = {"samples": body.get("audio_samples", [])}
    for s in sources:
        emit({"type": "source_start", "source": s})

    def on_result(r):
        emit({"type": "source_done", "result": r.as_dict()})

    def progress(key, i, n):
        emit({"type": "progress", "source": key, "i": i, "n": n})

    _peek.stop()
    if not _camera_lock.acquire(timeout=30):
        raise RuntimeError("camera is busy (another capture or health test is running)")
    try:
        return collect(sources, opts, on_result=on_result, progress=progress)
    finally:
        _camera_lock.release()


async def _run_ws(ws: WebSocket, work_fn):
    """Accept a websocket, read one JSON request, run work_fn(body, emit) on a thread, stream events."""
    await ws.accept()
    owner = owner_of(ws)
    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue()

    def emit(ev: dict):
        loop.call_soon_threadsafe(q.put_nowait, ev)

    try:
        body = json.loads(await ws.receive_text())
    except WebSocketDisconnect:
        return

    def work():
        try:
            body["_owner"] = owner
            work_fn(body, emit)
        except Exception as e:  # noqa: BLE001
            emit({"type": "error", "message": f"{type(e).__name__}: {e}"})
        emit({"type": "done"})

    threading.Thread(target=work, daemon=True).start()
    try:
        while True:
            ev = await q.get()
            await ws.send_text(json.dumps(ev))
            if ev["type"] == "done":
                break
    except WebSocketDisconnect:
        pass
    finally:
        try:
            await ws.close()
        except Exception:  # noqa: BLE001
            pass


@app.websocket("/ws/generate")
async def ws_generate(ws: WebSocket):
    def work(body, emit):
        if body["game"] not in GAMES:
            raise ValueError("unknown game")
        pool = _gather(body, emit)
        emit({"type": "pool", "pool": {k: v for k, v in pool.as_dict().items() if k != "seed"},
              "receipt": history.seed_hash(pool.seed)})
        req = _pick_request(body)
        n_tickets = max(1, min(20, int(body.get("tickets", 1))))
        st = None
        g = GAMES[req.game]
        if g.feed_id is not None and (req.strategy in ("hot", "cold", "pairs") or set(req.filters) & {"never_hit", "balanced"}):
            st = stats_mod.game_stats(req.game, current_era=req.current_era)
        if n_tickets == 1:
            picks = [generate(req, pool.seed, st)]
        else:
            picks = batch(req, pool.seed, n_tickets, max_shared=int(body.get("max_shared", 2)), stats=st)
        sh = history.save_pool(con, pool.as_dict())
        nd = schedule.next_draw(req.game)
        for p in picks:
            d = p.as_dict()
            tid = None
            if body.get("save", True):
                tid = history.save_ticket(con, d, pool.ok_sources, sh, pool.bits_in, shadow=bool(body.get("shadow")),
                                          label=body.get("label", ""), target_date=nd["date"] if nd else None,
                                          session=nd["session"] if nd else "", owner=body.get("_owner", "local"))
            emit({"type": "pick", "pick": d, "display": p.display(), "ticket_id": tid, "target": nd})

    await _run_ws(ws, work)


@app.websocket("/ws/tools")
async def ws_tools(ws: WebSocket):
    """Random numbers, passwords, keys. Results are never stored."""
    def work(body, emit):
        pool = _gather(body, emit)
        emit({"type": "pool", "pool": {k: v for k, v in pool.as_dict().items() if k != "seed"},
              "receipt": history.seed_hash(pool.seed)})
        kind = body.get("kind", "numbers")
        n_runs = max(1, min(50, int(body.get("runs", 1))))
        for i in range(n_runs):
            sub = hashlib.sha256(pool.seed + i.to_bytes(4, "big")).digest()
            emit({"type": "result", "kind": kind, "result": tools_mod.run_tool(kind, sub, body.get("opts", {}))})

    await _run_ws(ws, work)


@app.post("/api/crypto/encrypt")
def crypto_encrypt(body: dict):
    try:
        return {"token": tools_mod.encrypt_text(body.get("text", ""), body.get("password", ""))}
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.post("/api/crypto/decrypt")
def crypto_decrypt(body: dict):
    try:
        return {"text": tools_mod.decrypt_text(body.get("token", ""), body.get("password", ""))}
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


# ------------------------------------------------------------------ live camera peek (MJPEG)

class _Peek:
    """Owns the camera on a background thread for a bounded time; streams read the latest frame."""

    def __init__(self):
        self.thread: threading.Thread | None = None
        self.stop_ev = threading.Event()
        self.frame: bytes | None = None
        self.index = 0

    def start(self, index: int, seconds: float = 20.0) -> bool:
        self.stop()
        if not _camera_lock.acquire(timeout=3):
            return False
        self.stop_ev.clear()
        self.frame = None
        self.index = index

        def run():
            import cv2
            cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
            try:
                t_end = time.time() + seconds
                while not self.stop_ev.is_set() and time.time() < t_end and cap.isOpened():
                    ok, fr = cap.read()
                    if not ok:
                        break
                    ok, jpg = cv2.imencode(".jpg", fr, [cv2.IMWRITE_JPEG_QUALITY, 55])
                    if ok:
                        self.frame = jpg.tobytes()
                    time.sleep(0.04)
            finally:
                cap.release()
                self.frame = None
                _camera_lock.release()

        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()
        return True

    def stop(self):
        if self.thread and self.thread.is_alive():
            self.stop_ev.set()
            self.thread.join(timeout=5)
        self.thread = None

    def alive(self) -> bool:
        return bool(self.thread and self.thread.is_alive())


_peek = _Peek()


@app.get("/stream/camera/{index}")
def camera_stream(index: int):
    if HOSTED:
        raise HTTPException(404, "no server camera in hosted mode")
    if not _peek.start(index):
        raise HTTPException(409, "camera is busy")

    def gen():
        last = None
        while _peek.alive():
            fr = _peek.frame
            if fr is not None and fr is not last:
                last = fr
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + fr + b"\r\n"
            time.sleep(0.05)

    return StreamingResponse(gen(), media_type="multipart/x-mixed-replace; boundary=frame")


@app.post("/api/peek/stop")
def peek_stop():
    _peek.stop()
    return {"ok": True}


# ------------------------------------------------------------------ tickets

@app.get("/api/tickets")
def tickets(request: Request, game: str | None = None, limit: int = 200):
    return history.list_tickets(con, game=game, limit=limit, owner=owner_of(request))


@app.delete("/api/tickets/{tid}")
def delete_ticket(tid: int, request: Request):
    history.delete_ticket(con, tid, owner=owner_of(request))
    return {"ok": True}


@app.post("/api/tickets/bulk")
def save_bulk(body: dict, request: Request):
    """Save hand-made or wheeled tickets (no entropy pool)."""
    game = body["game"]
    if game not in GAMES:
        raise HTTPException(400, "unknown game")
    seed = hashlib.sha256(b"manual" + json.dumps(body, sort_keys=True).encode() + str(time.time()).encode()).digest()
    sh = history.save_pool(con, {"seed": seed.hex(), "created": time.time(), "bits_in": 0, "ok_sources": ["manual"],
                                 "failed_sources": [], "sources": []})
    nd = schedule.next_draw(game)
    ids = []
    for t in body["tickets"]:
        d = {"game": game, "main": t["main"], "bonus": t.get("bonus"), "strategy": body.get("strategy", "wheel"),
             "entropy": 0, "mode": "blend", "filters": []}
        ids.append(history.save_ticket(con, d, ["manual"], sh, 0, shadow=bool(body.get("shadow")),
                                       label=body.get("label", ""), target_date=nd["date"] if nd else None,
                                       session=nd["session"] if nd else "", owner=owner_of(request)))
    return {"ids": ids}


@app.post("/api/check")
def check(request: Request, game: str | None = None):
    return checker.check_all(con, game=game, owner=owner_of(request))


@app.get("/api/receipt/{sh}")
def receipt(sh: str):
    p = history.get_pool(con, sh)
    if not p:
        raise HTTPException(404, "no pool with that receipt")
    return p


@app.get("/api/trophies")
def trophies(request: Request):
    return history.trophies(con, owner=owner_of(request))


# ------------------------------------------------------------------ research

@app.get("/api/stats/{game}")
def stats(game: str, era: bool = True):
    if game not in GAMES:
        raise HTTPException(404, "unknown game")
    try:
        return stats_mod.game_stats(game, current_era=era)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, str(e)) from e


@app.get("/api/results/{game}")
def results(game: str, limit: int = 30):
    from ..feeds import get_draws
    if game not in GAMES or GAMES[game].feed_id is None:
        raise HTTPException(404, "no feed for this game")
    return [d.as_dict() for d in get_draws(game)[:limit]]


@app.get("/api/arena/{game}")
def arena(game: str, n: int = 300, window: int = 200, entropy: float = 0.3):
    import os
    return arena_mod.run_arena(game, n_draws=n, window=window, entropy=entropy, seed=os.urandom(32))


@app.post("/api/wheel")
def wheel(body: dict):
    import os
    game = body["game"]
    nums = [int(x) for x in body.get("numbers", [])]
    kind = body.get("kind", "abbrev")
    try:
        if kind == "full":
            tickets = wheel_mod.full_wheel(game, nums)
        elif kind == "key":
            tickets = wheel_mod.key_wheel(game, int(body["key"]), nums, os.urandom(32))
        else:
            tickets = wheel_mod.abbreviated_wheel(game, nums, int(body.get("guarantee", 3)), os.urandom(32))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"tickets": tickets, "count": len(tickets), "info": wheel_mod.wheel_info(game, len(set(nums)))}


@app.get("/api/health")
def health(sources: str = ""):
    sources = sources or ("cpu,anu,nist" if HOSTED else "cpu,camera,mic,anu,nist")
    out = {}
    _peek.stop()
    if not _camera_lock.acquire(timeout=30):
        raise HTTPException(409, "camera is busy")
    try:
        for k in sources.split(","):
            s = REGISTRY.get(k.strip())
            if not s or s.is_input:
                continue
            try:
                raw = s.gather(frames=16, seconds=1.0, n_bytes=8192) if not s.is_input else b""
                out[k] = {"ok": True, **health_report(raw), "detail": s._detail}
            except Exception as e:  # noqa: BLE001
                out[k] = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    finally:
        _camera_lock.release()
    return out


@app.get("/healthz")
def healthz():
    return {"ok": True, "hosted": HOSTED}


app.mount("/static", StaticFiles(directory=STATIC), name="static")


def main(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True):
    import uvicorn
    import webbrowser
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(f"http://{host}:{port}")).start()
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
