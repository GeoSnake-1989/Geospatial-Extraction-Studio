from __future__ import annotations

import json
import multiprocessing
import os
import socket
import threading
import time
import traceback
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

import uvicorn

from app.config import DATA_ROOT, ensure_data_directories
from app.main import app


HOST = "127.0.0.1"
DEFAULT_PORT = 8000
LAST_PORT = 8020


def configured_port() -> int | None:
    value = os.getenv("GES_BACKEND_PORT")
    if value is None:
        return None
    try:
        port = int(value)
    except ValueError as exc:
        raise RuntimeError("GES_BACKEND_PORT must be a valid TCP port number") from exc
    if not 1 <= port <= 65535:
        raise RuntimeError("GES_BACKEND_PORT must be between 1 and 65535")
    return port


def port_is_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        try:
            listener.bind((HOST, port))
        except OSError:
            return False
    return True


def studio_is_running(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://{HOST}:{port}/api/health", timeout=1) as response:
            payload = json.load(response)
    except (OSError, ValueError, urllib.error.URLError):
        return False
    return payload.get("status") == "ok" and payload.get("service") == "Geospatial Extraction Studio"


def select_port() -> tuple[int, bool]:
    requested = configured_port()
    candidates = [requested] if requested is not None else list(range(DEFAULT_PORT, LAST_PORT + 1))
    for port in candidates:
        if studio_is_running(port):
            return port, True
        if port_is_available(port):
            return port, False
    if requested is not None:
        raise RuntimeError(f"Configured backend port {requested} is already in use")
    raise RuntimeError(f"No available application port was found between {DEFAULT_PORT} and {LAST_PORT}")


def open_browser_when_ready(port: int) -> None:
    health_url = f"http://{HOST}:{port}/api/health"
    application_url = f"http://{HOST}:{port}/"
    for _ in range(80):
        if studio_is_running(port):
            webbrowser.open(application_url)
            return
        time.sleep(0.25)
    Path(DATA_ROOT, "logs", "launcher-error.log").write_text(
        f"The application did not become ready at {health_url}.\n",
        encoding="utf-8",
    )


def main() -> int:
    multiprocessing.freeze_support()
    ensure_data_directories()
    (DATA_ROOT / "logs").mkdir(parents=True, exist_ok=True)

    port, already_running = select_port()
    application_url = f"http://{HOST}:{port}/"
    if already_running:
        webbrowser.open(application_url)
        return 0

    if os.getenv("GES_NO_BROWSER") != "1":
        threading.Thread(target=open_browser_when_ready, args=(port,), daemon=True).start()
    uvicorn.run(app, host=HOST, port=port, log_level="info", access_log=False)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BaseException:
        log_directory = DATA_ROOT / "logs"
        log_directory.mkdir(parents=True, exist_ok=True)
        with (log_directory / "launcher-error.log").open("a", encoding="utf-8") as stream:
            traceback.print_exc(file=stream)
        raise