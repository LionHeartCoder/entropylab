@echo off
cd /d "%~dp0"
title Entropy Lab
echo Starting Entropy Lab at http://127.0.0.1:8765 ...
uv run lotto serve --port 8765
pause
