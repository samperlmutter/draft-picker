from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


class Storage:
    def __init__(self, root: Path):
        self.root = root
        self.state_path = root / "draft-state.json"
        self.events_path = root / "pick-events.jsonl"
        self.pid_path = root / "monitor.pid"

    @classmethod
    def from_environment(cls) -> "Storage":
        raw = os.environ.get("DRAFT_ADVISOR_RUNTIME_DIR")
        root = Path(raw) if raw else Path.home() / ".local" / "state" / "draft-advisor"
        root.mkdir(parents=True, exist_ok=True)
        return cls(root)

    def read_state(self) -> dict[str, Any]:
        try:
            return json.loads(self.state_path.read_text())
        except FileNotFoundError as exc:
            raise ValueError("no Draft State is available; start the monitor first") from exc
        except json.JSONDecodeError as exc:
            raise ValueError("stored Draft State is invalid") from exc

    def write_state(self, state: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        fd, raw_path = tempfile.mkstemp(prefix=".draft-state-", suffix=".json", dir=self.root)
        path = Path(raw_path)
        try:
            with os.fdopen(fd, "w") as handle:
                json.dump(state, handle, sort_keys=True, separators=(",", ":"))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(path, self.state_path)
        finally:
            path.unlink(missing_ok=True)

    def append_events(self, events: list[dict[str, Any]]) -> None:
        if not events:
            return
        with self.events_path.open("a") as handle:
            for event in events:
                handle.write(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
