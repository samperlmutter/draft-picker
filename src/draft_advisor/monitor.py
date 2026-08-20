from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from .config import Config
from .sleeper import SleeperClient
from .state import fetch_state
from .storage import Storage


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def monitor_pid(storage: Storage) -> int | None:
    try:
        pid = int(storage.pid_path.read_text().strip())
    except (FileNotFoundError, ValueError):
        return None
    if _pid_alive(pid):
        return pid
    storage.pid_path.unlink(missing_ok=True)
    return None


def refresh(config: Config, storage: Storage, client: SleeperClient | None = None) -> dict:
    previous = None
    try:
        previous = storage.read_state()
    except ValueError:
        pass
    state, events = fetch_state(config, client or SleeperClient(), previous)
    storage.append_events(events)
    storage.write_state(state)
    return state


def start(config_path: str | None, storage: Storage, config: Config) -> tuple[int, bool]:
    running = monitor_pid(storage)
    if running:
        return running, False
    command = [sys.executable, "-m", "draft_advisor"]
    if config_path:
        command += ["--config", config_path]
    command += ["monitor", "run"]
    env = os.environ.copy()
    source_root = str(Path(__file__).resolve().parents[1])
    env["PYTHONPATH"] = source_root + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    try:
        previous_state_mtime = storage.state_path.stat().st_mtime_ns
    except FileNotFoundError:
        previous_state_mtime = -1
    process = subprocess.Popen(command, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            refreshed = storage.state_path.stat().st_mtime_ns > previous_state_mtime
        except FileNotFoundError:
            refreshed = False
        if refreshed and monitor_pid(storage) == process.pid:
            return process.pid, True
        if process.poll() is not None:
            raise ValueError("monitor failed to start; run `monitor run` to inspect the error")
        time.sleep(0.05)
    process.terminate()
    raise ValueError("monitor did not produce Draft State within 10 seconds")


def stop(storage: Storage) -> bool:
    pid = monitor_pid(storage)
    if not pid:
        return False
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and _pid_alive(pid):
        time.sleep(0.05)
    storage.pid_path.unlink(missing_ok=True)
    return True


def run(config: Config, storage: Storage) -> None:
    existing = monitor_pid(storage)
    if existing and existing != os.getpid():
        raise ValueError(f"monitor is already running (pid {existing})")
    storage.pid_path.write_text(f"{os.getpid()}\n")
    stopping = False

    def request_stop(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    max_polls = int(os.environ.get("DRAFT_ADVISOR_MAX_POLLS", "0"))
    polls = 0
    try:
        while not stopping:
            state = refresh(config, storage)
            polls += 1
            if state["draft"]["status"] == "complete" or (max_polls and polls >= max_polls):
                break
            time.sleep(config.poll_interval_seconds)
    finally:
        if monitor_pid(storage) == os.getpid():
            storage.pid_path.unlink(missing_ok=True)
