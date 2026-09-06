"""Deploy Entropy Lab to Modal.

    uv tool install modal      # once
    modal setup                # once, signs you in
    modal deploy modal_app.py  # prints the public URL

Runs the same FastAPI app in hosted mode: the visitor's browser captures camera
and microphone, tickets are separated per visitor by an anonymous cookie, and
the SQLite database plus the results cache live on a persistent Modal volume.
"""
from pathlib import Path

import modal

ROOT = Path(__file__).parent

image = (
    modal.Image.debian_slim(python_version="3.13")
    .apt_install("libglib2.0-0")
    .pip_install(
        "fastapi>=0.115",
        "uvicorn[standard]>=0.30",
        "numpy>=2.0",
        "opencv-python-headless>=4.10",
        "httpx>=0.27",
        "cryptography>=43",
        "typer>=0.12",
        "tzdata",
    )
    .env({"LOTTO_HOSTED": "1", "LOTTO_DATA_DIR": "/data", "PYTHONPATH": "/root/app/src"})
    .add_local_dir(ROOT / "src", remote_path="/root/app/src")
    .add_local_file(ROOT / "data" / "eff_large_wordlist.txt", remote_path="/root/app/data/eff_large_wordlist.txt")
)

app = modal.App("entropylab", image=image)
volume = modal.Volume.from_name("entropylab-data", create_if_missing=True)


@app.function(
    volumes={"/data": volume},
    min_containers=0,
    scaledown_window=300,
    timeout=600,
    max_containers=2,
)
@modal.concurrent(max_inputs=50)
@modal.asgi_app()
def web():
    import os
    import sys

    sys.path.insert(0, "/root/app/src")
    os.environ.setdefault("LOTTO_HOSTED", "1")
    os.environ.setdefault("LOTTO_DATA_DIR", "/data")
    from lotto import tools

    tools.WORDLIST_PATH = Path("/root/app/data/eff_large_wordlist.txt")
    from lotto.web.app import app as fastapi_app

    return fastapi_app
